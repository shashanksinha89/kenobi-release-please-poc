def tenant_middleware(request, call_next):
    return call_next(request)
