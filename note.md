

Run on 0.0.0.0
```bash
BIND=0.0.0.0  docker compose -f docker-compose.yml -f docker-compose.build.yml up -d
```


Build for development

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
```


Down

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml down -v
```