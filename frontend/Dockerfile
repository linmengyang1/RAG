FROM node:18-alpine

WORKDIR /app

# 先复制 package.json（利用 Docker 缓存）
COPY package.json ./

# 安装依赖
RUN npm install --legacy-peer-deps

# 复制项目文件（docker-compose 会用 volume 覆盖，但 build 时需要源码）
COPY . .

# 环境变量
ENV NEXT_PUBLIC_API_BASE=http://localhost:18000
ENV PORT=3000
ENV HOST=0.0.0.0

EXPOSE 3000

# 开发模式
CMD ["npm", "run", "dev"]
