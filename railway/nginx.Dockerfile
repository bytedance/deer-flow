FROM nginx:alpine

RUN apk add --no-cache gettext

COPY railway/templates/nginx.railway.conf.template /etc/nginx/nginx.conf.template
COPY railway/start-nginx.sh /start-nginx.sh

RUN chmod +x /start-nginx.sh

EXPOSE 8080

CMD ["/start-nginx.sh"]
