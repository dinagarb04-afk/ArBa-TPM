FROM node:22-alpine AS dependencies
WORKDIR /app
COPY frontend/package.json ./
RUN npm install

FROM dependencies AS development
COPY frontend ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM dependencies AS build
COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
