FROM node:24-alpine

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend ./

ENV SERVER_API_BASE_URL=http://backend:8000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

