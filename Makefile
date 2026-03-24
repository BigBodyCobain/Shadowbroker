.PHONY: up-local up-lan down restart-local restart-lan logs status help

COMPOSE = docker compose

# Detect LAN IP (tries Wi-Fi first, falls back to Ethernet)
LAN_IP := $(shell ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

## Default target — print help
help:
	@echo ""
	@echo "Shadowbroker taskrunner"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "  up-local        Start with loopback binding (local access only)"
	@echo "  up-lan          Start with 0.0.0.0 binding (LAN accessible)"
	@echo "  down            Stop all containers"
	@echo "  restart-local   Bounce and restart in local mode"
	@echo "  restart-lan     Bounce and restart in LAN mode"
	@echo "  logs            Tail logs for all services"
	@echo "  status          Show container status"
	@echo ""

## Start in local-only mode (loopback only)
up-local:
	BIND=127.0.0.1 $(COMPOSE) up -d

## Start in LAN mode (accessible to other hosts on the network)
up-lan:
	@if [ -z "$(LAN_IP)" ]; then \
		echo "ERROR: Could not detect LAN IP. Check your network connection."; \
		exit 1; \
	fi
	@echo "Detected LAN IP: $(LAN_IP)"
	BIND=0.0.0.0 CORS_ORIGINS=http://$(LAN_IP):3000 $(COMPOSE) up -d
	@echo ""
	@echo "Shadowbroker is now running and can be accessed by LAN devices at http://$(LAN_IP):3000"

## Stop all containers
down:
	$(COMPOSE) down

## Restart in local-only mode
restart-local: down up-local

## Restart in LAN mode
restart-lan: down up-lan

## Tail logs for all services
logs:
	$(COMPOSE) logs -f

## Show running container status
status:
	$(COMPOSE) ps
