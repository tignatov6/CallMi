Запуск:
```
uvicorn app:app --reload
```
or
```
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Deploy:
```
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```
