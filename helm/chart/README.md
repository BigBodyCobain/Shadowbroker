# ShadowBroker Helm Chart

A Helm chart for deploying ShadowBroker services (backend and frontend).

## Prerequisites

- Helm >= 3.0
- Kubernetes cluster with access to the `bjw-s-labs` Helm repository
- Your OWN ingress controller, Gateway API, etc

[`ingress-nginx` has been deprecated and as of writing this](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/) we do not feel comfortable hard-coding in an ingress implementation!

Consider using ingress controllers like Traefik and Cert-Manager for automatic SSL/TLS termination and dynamic route management.

- [traefik](https://traefik.io/traefik)
- [cert-manager](https://cert-manager.io/)

## Installation

### Add the Helm repository

```bash
helm repo add bjw-s-labs https://bjw-s-labs.github.io/helm-charts/
helm repo update
```

### Install the chart

```bash
helm install shadowbroker ./chart --create-namespace
```

Or use the repository:

```bash
helm install shadowbroker bjw-s-labs/app-template \
  --namespace shadowbroker \
  -f values.yaml
```

## Configuration

### Backend Service

The backend deployment runs with the following settings by default:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `controllers.backend.type` | Controller type | `deployment` |
| `controllers.backend.strategy` | Update strategy | `RollingUpdate` |
| `controllers.backend.rollingUpdate.unavailable` | Max unavailable during update | `1` |
| `controllers.backend.containers.main.runAsUser` | Security context user | `1001` |
| `controllers.backend.containers.main.runAsGroup` | Security context group | `1001` |
| `controllers.backend.containers.main.image.repository` | Container image | `registry.gitlab.com/bigbodycobain/shadowbroker/backend` (or `ghcr.io/bigbodycobain/shadowbroker-backend`) |
| `controllers.backend.containers.main.image.tag` | Container tag | `latest` |
| `controllers.backend.service.type` | Service type | `ClusterIP` |
| `controllers.backend.service.ports.http.port` | HTTP port | `8000` |

#### Backend Environment Variables

The following environment variables are configured via secrets:

- `AIS_API_KEY` - API key for AIS service
- `OPENSKY_CLIENT_ID` - OpenSky client ID
- `OPENSKY_CLIENT_SECRET` - OpenSky client secret

These can be injected using a Secret resource or Kubernetes ConfigMap.

### Frontend Service

The frontend deployment configuration:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `controllers.frontend.type` | Controller type | `deployment` |
| `controllers.frontend.strategy` | Update strategy | `RollingUpdate` |
| `controllers.frontend.rollingUpdate.unavailable` | Max unavailable during update | `1` |
| `controllers.frontend.containers.main.runAsUser` | Security context user | `1001` |
| `controllers.frontend.containers.main.runAsGroup` | Security context group | `1001` |
| `controllers.frontend.containers.main.image.repository` | Container image | `registry.gitlab.com/bigbodycobain/shadowbroker/frontend` (or `ghcr.io/bigbodycobain/shadowbroker-frontend`) |
| `controllers.frontend.containers.main.image.tag` | Container tag | `latest` |

#### Frontend Environment Variables

- `BACKEND_URL` - Backend API URL (defaults to Kubernetes service discovery)

### Service Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.backend.type` | Service type | `ClusterIP` |
| `service.backend.ports.http.port` | Backend HTTP port | `8000` |
| `service.frontend.type` | Service type | `ClusterIP` |
| `service.frontend.ports.http.port` | Frontend HTTP port | `3000` |

## Uninstall

```bash
helm uninstall shadowbroker -n shadowbroker
```

## Development

For development with local images, modify the image paths and tags:

```yaml
controllers:
  backend:
    containers:
      main:
        image:
          repository: localhost/my-backend-image
          tag: dev-latest
  frontend:
    containers:
      main:
        image:
          repository: localhost/my-frontend-image
          tag: dev-latest
```

## Values Schema

This chart uses the `app-template` Helm chart as a base. Refer to the [app-template documentation](https://bjw-s-labs.github.io/helm-charts/) for additional customization options.
