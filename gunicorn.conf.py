import multiprocessing

bind = "0.0.0.0:8000"
workers = min(multiprocessing.cpu_count(), 4)
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 600  # Claude operations can be long
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
