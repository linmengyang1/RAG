.PHONY: help up down logs ps init-db init-milvus ingest backend-shell backend-run backend-test frontend-install frontend-up frontend-build frontend-logs frontend-shell clean

# 默认从 .env 读取（不存在则用 .env.example）
DOTENV := $(shell test -f .env && echo .env || echo .env.example)

help: ## 显示所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## 启动所有服务（后台）
	docker compose --env-file $(DOTENV) up -d

down: ## 停止所有服务
	docker compose --env-file $(DOTENV) down

logs: ## 查看日志（实时）
	docker compose logs -f --tail=100

ps: ## 查看服务状态
	docker compose ps

build: ## 构建后端镜像
	docker compose build backend

init-db: ## 初始化数据库（Milvus 集合 + PG 已由 init.sql 自动建表）
	docker compose exec backend python /app/infra/scripts/init_milvus.py

init-milvus: ## 仅初始化 Milvus 集合
	docker compose exec backend python /app/infra/scripts/init_milvus.py

init-milvus-force: ## 强制重建 Milvus 集合（会清空数据）
	docker compose exec backend python /app/infra/scripts/init_milvus.py --force

ingest: ## 运行数据接入管线（默认摄入 10% 数据：md 24 + pdf 5）
	docker compose exec backend python -m app.cli.ingest --limit-md 24 --limit-pdf 5

ingest-all: ## 全量摄入（不限制数量，慎用）
	docker compose exec backend python -m app.cli.ingest

backend-shell: ## 进入后端容器 shell
	docker compose exec backend bash

backend-run: ## 本地直接运行后端（开发调试用，端口 18000）
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 18000

backend-test: ## 运行后端测试
	docker compose exec backend pytest

test-local: ## 本机直接跑测试（不走 docker）
	cd backend && pytest tests/ -v

frontend-install: ## 安装前端依赖（首次或 package.json 变更后）
	docker compose exec frontend npm install

frontend-up: ## 启动前端服务（首次会构建镜像）
	docker compose up -d frontend

frontend-build: ## 构建前端生产镜像
	docker compose build frontend

frontend-logs: ## 查看前端日志
	docker compose logs -f frontend

frontend-shell: ## 进入前端容器 shell
	docker compose exec frontend sh

clean: ## 清理容器与卷（慎用，会删数据）
	docker compose down -v
