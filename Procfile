release: cd django_backend && python manage.py migrate --noinput
web: cd django_backend && gunicorn django_backend.wsgi --bind 0.0.0.0:$PORT --log-file -
