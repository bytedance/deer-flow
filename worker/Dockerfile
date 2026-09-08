FROM node:20-bullseye

# Install ffmpeg for composition
RUN apt-get update && apt-get install -y ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY . .

CMD ["node", "worker/index.js"]
