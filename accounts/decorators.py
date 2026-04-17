from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from functools import wraps

def role_required(roles=[]):
    """
    Decorator to restrict access to a view based on user groups.
    If the user has 'is_superuser' status, they always pass.
    Otherwise, they must be in at least one of the specified roles.
    If the request is an AJAX/API call (JSON), it returns a 403 JsonResponse.
    Otherwise, it raises PermissionDenied (which triggers standard 403 pages).
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if request.headers.get('Content-Type') == 'application/json':
                    return JsonResponse({'error': 'Unauthorized'}, status=401)
                raise PermissionDenied

            has_perm = False
            if request.user.is_superuser:
                has_perm = True
            elif request.user.groups.filter(name__in=roles).exists():
                has_perm = True

            if not has_perm:
                if request.headers.get('Content-Type') == 'application/json':
                    return JsonResponse({'error': f'Permission denied. Required roles: {", ".join(roles)}'}, status=403)
                raise PermissionDenied
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
