# AI Learning Lab Containerization & AWS EKS Deployment Guide

## Purpose and Scope
This guide scopes the level of effort (LoE) and provides a reference plan for packaging AI Learning Lab into containers and deploying the stack onto Amazon Elastic Kubernetes Service (EKS). It covers:

- Application components and runtime assumptions relevant to containerization.
- Container build strategy and supporting assets.
- Kubernetes deployment architecture for EKS, including ingress and observability.
- Options for database (DB) and authentication (Auth) services in AWS.
- Implementation roadmap with estimated effort ranges.

The document is intentionally detailed so it can be shared with stakeholders to estimate work, allocate ownership, and track progress.

---

## Application Overview
The project is a FastAPI backend (`backend/app/main.py`) that serves both API routes and the static frontend (`frontend/`).【F:ARCHITECTURE.md†L6-L68】 Key details:

- **Runtime**: Python 3.11 (per `requirements.txt`).
- **State**: Local SQLite database (`local.db`) storing conversations, characters, messages, and encrypted API secrets.【F:ARCHITECTURE.md†L69-L85】
- **Static assets**: Served from `frontend/assets/` via FastAPI static mount.【F:ARCHITECTURE.md†L11-L25】
- **Configuration**: API keys are usually entered via the UI and stored in the DB, with an optional `.env` loading pathway gated by `ALLOW_ENV_SECRETS` for development.【F:README.md†L12-L48】

When containerizing, we must package the backend, copy the frontend assets into the image, and expose the FastAPI service on port 8000 (default).

---

## Containerization Strategy

### High-Level Tasks & LoE
| Task | Description | Est. Effort |
| --- | --- | --- |
| Baseline Dockerfile | Create production-grade Dockerfile with multi-stage build and non-root runtime. | 1–2 days |
| Dependency locking | Ensure `requirements*.txt` cover runtime needs; optionally generate hash-locked files. | 0.5 day |
| Runtime configuration | Externalize environment variables (OpenAI, ElevenLabs, etc.) and DB URL. | 0.5–1 day |
| Local docker-compose | Create compose file for local parity with prod (DB + app). | 1 day |
| CI build & scan | Add pipeline job to build/push image, run security scan (e.g., Trivy). | 1–2 days |
| Documentation | Update README/ops docs with runbooks. | 0.5 day |

> **Total Initial LoE**: ~4–6 engineering days for a first production-ready container, assuming familiarity with Docker and FastAPI deployments.

### Reference Dockerfile
```dockerfile
# syntax=docker/dockerfile:1.4
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies separately for better layer caching
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Optional: install dev-only packages for migrations/tests in a separate stage
# COPY requirements-dev.txt requirements-dev.txt
# RUN pip install -r requirements-dev.txt

COPY backend backend
COPY frontend frontend
COPY ARCHITECTURE.md README.md ./

# Non-root runtime
RUN useradd -m appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Enhancements & Hardening
- **Multi-stage build**: Add a builder stage to compile wheels, then copy site-packages into a slim runtime to reduce image size.
- **Static asset build**: If a future SPA build step emerges (e.g., bundler), incorporate it into the builder stage.
- **Health checks**: Implement `/healthz` endpoint and use Docker `HEALTHCHECK` for readiness verification.
- **Non-root + read-only rootfs**: Already running as `appuser`; consider remounting root filesystem read-only with writable directories mounted via volumes.
- **Image scanning**: Integrate Trivy/Grype into CI to detect vulnerabilities.

### Local Development Workflow
1. Create `.env.docker` with required secrets (OpenAI, ElevenLabs, DB connection string).
2. Start dependencies with Docker Compose:
   ```yaml
   version: "3.9"
   services:
     app:
       build: .
       ports:
         - "8000:8000"
       env_file: .env.docker
       depends_on:
         - db
     db:
       image: postgres:15
       environment:
         POSTGRES_DB: ailab
         POSTGRES_USER: ailab
         POSTGRES_PASSWORD: changeme
       volumes:
         - db_data:/var/lib/postgresql/data
   volumes:
     db_data:
   ```
3. Run database migrations (if added) using Alembic/SQLAlchemy scripts.
4. Access the app at `http://localhost:8000` to validate parity with production.

---

## AWS EKS Deployment Architecture

### Target Topology
- **Container Registry**: Amazon Elastic Container Registry (ECR) for image storage.
- **Cluster**: Managed node group using Bottlerocket or Amazon Linux 2 AMIs.
- **Workloads**: Kubernetes Deployment for the FastAPI app, optional CronJobs for maintenance tasks (e.g., DB backups).
- **Networking**: AWS Load Balancer Controller provisioning an Application Load Balancer (ALB) via Ingress.
- **Secrets**: AWS Secrets Manager or SSM Parameter Store integrated via CSI driver.
- **Observability**: CloudWatch Container Insights or OpenTelemetry Collector.

### Deployment Steps
1. **Provision Infrastructure** (Terraform or eksctl):
   - Create ECR repository `ai-learning-lab`.
   - Stand up EKS cluster with appropriate IAM roles and node groups.
   - Install AWS Load Balancer Controller, ExternalDNS (if using Route53), and Secrets Store CSI Driver.

2. **CI/CD Pipeline**:
   - Build Docker image on push (`docker build`).
   - Authenticate to ECR (`aws ecr get-login-password`).
   - Push image (`docker push <account>.dkr.ecr.<region>.amazonaws.com/ai-learning-lab:<tag>`).
   - Trigger Kubernetes deploy via GitHub Actions, CodePipeline, or Argo CD.

3. **Kubernetes Manifests** (Helm chart recommended):
   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: ai-learning-lab
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: ai-learning-lab
     template:
       metadata:
         labels:
           app: ai-learning-lab
       spec:
         serviceAccountName: ai-learning-lab
         containers:
           - name: web
             image: <account>.dkr.ecr.<region>.amazonaws.com/ai-learning-lab:<tag>
             ports:
               - containerPort: 8000
             env:
               - name: DATABASE_URL
                 valueFrom:
                   secretKeyRef:
                     name: db-credentials
                     key: url
               - name: ALLOW_ENV_SECRETS
                 value: "0"
             readinessProbe:
               httpGet:
                 path: /healthz
                 port: 8000
               initialDelaySeconds: 5
               periodSeconds: 10
             livenessProbe:
               httpGet:
                 path: /healthz
                 port: 8000
               initialDelaySeconds: 30
               periodSeconds: 30
   ---
   apiVersion: v1
   kind: Service
   metadata:
     name: ai-learning-lab
   spec:
     type: ClusterIP
     selector:
       app: ai-learning-lab
     ports:
       - port: 80
         targetPort: 8000
   ---
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: ai-learning-lab
     annotations:
       kubernetes.io/ingress.class: alb
       alb.ingress.kubernetes.io/scheme: internet-facing
   spec:
     rules:
       - host: ai-learning-lab.example.com
         http:
           paths:
             - path: /
               pathType: Prefix
               backend:
                 service:
                   name: ai-learning-lab
                   port:
                     number: 80
   ```

4. **Secret Management**:
   - Store OpenAI, ElevenLabs keys in Secrets Manager. Use CSI driver to mount them as environment variables or files.
   - Consider enabling envelope encryption for sensitive data at rest.

5. **Scaling & Resilience**:
   - Configure Horizontal Pod Autoscaler (HPA) based on CPU/memory or custom metrics (request rate).
   - Set PodDisruptionBudget to avoid total outages during node maintenance.
   - Use multi-AZ managed node groups for HA.

6. **Observability & Operations**:
   - Forward logs using Fluent Bit to CloudWatch or OpenSearch.
   - Define SLOs for response latency and error rate.
   - Add dashboards/alerts for 5xx responses, queue backlogs, and API provider quota usage.

---

## Database Options

| Option | Pros | Cons | Recommended Use |
| --- | --- | --- | --- |
| **Amazon RDS for PostgreSQL** | Managed backups, high availability (Multi-AZ), compatible with SQLAlchemy. | Higher cost than SQLite, requires migration scripts. | Default production choice when multi-user persistence is required. |
| **Amazon Aurora Serverless v2 (PostgreSQL compatible)** | Auto-scaling capacity, pay-per-use, global database options. | Cold-start latency, more complex IAM setup. | Spiky workloads or expected growth beyond RDS. |
| **SQLite (container volume)** | Zero setup, matches current code. | Single-writer lock contention, lacks HA/backup story, not recommended for multi-pod deployments. | Short-term dev/test only. |
| **Amazon DynamoDB** | Fully managed, scales automatically. | Requires significant refactor away from SQLAlchemy models. | Long-term re-architecture for serverless scale if relational constraints are unnecessary. |

### Migration Considerations
- Introduce SQLAlchemy URL configuration via `DATABASE_URL` environment variable.
- Add migrations (Alembic) to manage schema evolution when moving to Postgres.
- For production, disable `.env` pathway (`ALLOW_ENV_SECRETS=0`) and rely on managed secrets.
- Implement backup strategy (RDS automated backups + point-in-time recovery).
- Optionally use AWS DMS to import legacy SQLite data after exporting to CSV.

---

## Authentication Options

| Approach | Description | Pros | Cons | LoE |
| --- | --- | --- | --- | --- |
| **AWS Cognito Hosted UI** | Use Cognito user pools with hosted UI; integrate via OAuth/OpenID Connect. | Managed MFA, password policies, social login. | Requires frontend changes (login flow, token storage). | 3–4 days |
| **Cognito + API Gateway** | Place API Gateway in front of EKS service with Cognito authorizers. | Centralized auth, rate limiting, WAF. | Adds latency; requires public endpoint reconfiguration. | 5–7 days |
| **Third-party (Auth0, Okta)** | External IdP integrated via OIDC. | Rich features, easy UI. | Additional cost, vendor lock-in. | 3–5 days |
| **Custom JWT** | Build own login, store hashed credentials in DB. | Full control, offline capability. | Security burden, compliance risk. | 7+ days |

### Recommended Path
1. Start with Cognito user pool + hosted UI.
2. Modify frontend to require login before accessing chat UI; store ID token in memory.
3. Add FastAPI dependency to validate JWT (e.g., `fastapi-cognito` or `python-jose`).
4. Restrict API routes to authenticated users; map Cognito sub to conversation ownership.
5. For admin operations, leverage Cognito groups/roles.

For service-to-service calls (e.g., workers), use IAM roles for service accounts (IRSA) and short-lived credentials.

---

## Implementation Roadmap

1. **Preparation (1–2 days)**
   - Confirm target AWS account/region, DNS, SSL requirements.
   - Decide on DB and Auth approach (RDS + Cognito recommended).
   - Set up infrastructure-as-code baseline (Terraform modules or CDK).

2. **Containerization (4–6 days)**
   - Implement Dockerfile and docker-compose for local dev.
   - Update FastAPI config to read `DATABASE_URL`, `SECRET_MANAGER_ARN`, etc.
   - Document environment variables and secrets contract.

3. **Database Migration (3–5 days)**
   - Provision RDS Postgres (dev/stage/prod).
   - Add Alembic migrations and migration scripts.
   - Test data import/export flows.

4. **Auth Integration (3–5 days)**
   - Configure Cognito user pool, hosted domain, app client.
   - Update frontend login flow and backend token validation middleware.
   - Implement authorization checks on conversation resources.

5. **EKS Deployment (5–8 days)**
   - Build Helm chart or Kustomize overlays (dev/stage/prod).
   - Configure Ingress/ALB, HTTPS (ACM), DNS (Route53).
   - Set up IRSA for Secrets Manager access, logging, autoscaling.

6. **Operational Hardening (3–4 days)**
   - Add monitoring dashboards, alerts, log retention policies.
   - Run load tests; tune HPA and Pod resources.
   - Implement backup/restore runbooks for DB and secrets.

> **Overall Estimated Effort**: ~19–30 engineering days depending on team familiarity with AWS, Terraform, and Kubernetes. Parallel streams (e.g., auth and DB) can reduce calendar time.

---

## Additional Recommendations
- **Environment Strategy**: Maintain isolated dev, staging, and prod namespaces with separate DB instances. Use feature flags for experimental LLM providers.
- **Cost Controls**: Enable autoscaling down to zero in non-prod (with Fargate profiles or smaller node groups). Schedule nightly shutdowns when appropriate.
- **Security**: Enforce TLS 1.2+, use AWS WAF on the ALB, and enable GuardDuty/Inspector. Rotate API keys regularly and monitor for quota exhaustion from upstream providers.
- **Disaster Recovery**: Document RPO/RTO targets. Enable multi-AZ for DB, replicate secrets, and test restoration procedures quarterly.
- **Compliance**: If handling child data, ensure COPPA considerations—log user consent, mask personal data, and restrict data retention.

---

## Reference Checklist
- [ ] Dockerfile optimized, images built and scanned.
- [ ] CI/CD pushes images to ECR with immutable tags.
- [ ] Kubernetes manifests templated (Helm) and deployed via GitOps.
- [ ] Secrets sourced from AWS Secrets Manager via CSI driver.
- [ ] Managed Postgres configured with migrations and backups.
- [ ] Cognito auth integrated end-to-end.
- [ ] Monitoring/alerting dashboards in place.
- [ ] Runbooks for deploy, rollback, and incident response documented.

Completing this checklist will result in a production-ready, containerized deployment of AI Learning Lab on AWS EKS.
