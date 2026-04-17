from django import template
from django.contrib.auth.models import Group

register = template.Library()

@register.filter(name='has_role')
def has_role(user, group_names):
    """
    Check if user belongs to one of the comma-separated group_names.
    Usage in template: {% if request.user|has_role:"Admin,Operator" %}
    Also handles superusers as having all roles.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
        
    roles = [role.strip() for role in group_names.split(',')]
    return user.groups.filter(name__in=roles).exists()
