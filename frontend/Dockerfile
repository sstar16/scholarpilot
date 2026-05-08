FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json ./
# 国内加速：换 npmmirror 避免 registry.npmjs.org 被墙/慢
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
