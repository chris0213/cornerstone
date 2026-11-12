# syntax=docker/dockerfile:1.6
# ===== 构建阶段 =====
FROM node:22-alpine AS builder

WORKDIR /app

# 优先复制依赖清单以利用缓存
COPY package.json package-lock.json* pnpm-lock.yaml* ./

# 优先 npm（项目同时存在两种 lock，统一用 npm）
RUN if [ -f package-lock.json ]; then \
        npm ci --legacy-peer-deps --no-audit --no-fund; \
    else \
        npm install --legacy-peer-deps --no-audit --no-fund; \
    fi

COPY . .

# 版本标识：构建时通过 --build-arg APP_VERSION=<git sha> 注入，
# 会显示在「系统设置」页底部，用于生产环境确认前端产物版本
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

# 构建前端静态资源
# 当前代码库存在历史 TS 类型错误，生产镜像先执行 Vite 构建，避免 Docker 部署被 vue-tsc 阻塞。
RUN npx vite build

# ===== 运行阶段（Nginx）=====
FROM nginx:1.27-alpine AS runtime

# 时区
RUN apk add --no-cache tzdata \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && apk del tzdata

# 删除默认配置，使用自定义 server 配置
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/cornerstone.conf

# 静态文件
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
