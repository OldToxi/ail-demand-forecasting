FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/out /usr/share/nginx/html
COPY data/outputs/forecast/ui/forecast_ui.json /usr/share/nginx/api/forecast_ui.json
COPY data/outputs/forecast/ui/forecast_ui_ACL.json /usr/share/nginx/api/forecast_ui_ACL.json
COPY data/outputs/forecast/ui/planner_adjustments.json /usr/share/nginx/api/planner_adjustments.json
COPY forecasting/templates/planner_adjustments_template.csv /usr/share/nginx/api/planner_adjustments_template.csv
EXPOSE 3000
