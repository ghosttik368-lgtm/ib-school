"""Client IP supplied by our Caddy, which replaces this header on every request."""
from ipaddress import ip_address


class ProxyClientIPMiddleware:
    def __init__(self, get_response): self.get_response = get_response

    def __call__(self, request):
        value = request.META.get('HTTP_X_IB_CLIENT_IP', '')
        try:
            request.META['REMOTE_ADDR'] = str(ip_address(value))
        except ValueError:
            pass
        return self.get_response(request)
