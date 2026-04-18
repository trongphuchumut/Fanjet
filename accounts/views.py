from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from .forms import LoginForm

# ─── Cấu hình Rate Limiting ────────────────────────────────────────────────────
MAX_ATTEMPTS = 5          # Số lần sai tối đa
LOCKOUT_MINUTES = 10      # Thời gian khóa (phút)
LOCKOUT_SECONDS = LOCKOUT_MINUTES * 60


def _get_client_ip(request):
    """Lấy IP thực của client (hỗ trợ reverse proxy)."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:home')

    ip = _get_client_ip(request)
    lockout_key = f'login_lockout_{ip}'
    attempts_key = f'login_attempts_{ip}'

    # Kiểm tra có đang bị khóa không
    if cache.get(lockout_key):
        messages.error(
            request,
            f'Tài khoản bị tạm khóa do đăng nhập sai quá nhiều lần. '
            f'Vui lòng thử lại sau {LOCKOUT_MINUTES} phút.'
        )
        return render(request, 'accounts/login.html', {'form': LoginForm(), 'locked': True})

    form = LoginForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            remember_me = form.cleaned_data.get('remember_me', False)

            user = authenticate(request, username=username, password=password)

            if user is not None:
                # Đăng nhập thành công → xóa bộ đếm
                cache.delete(attempts_key)
                cache.delete(lockout_key)
                login(request, user)
                if not remember_me:
                    request.session.set_expiry(0)
                messages.success(request, f'Chào mừng trở lại, {user.get_full_name() or user.username}!')
                next_url = request.GET.get('next', 'dashboard:home')
                return redirect(next_url)
            else:
                # Đăng nhập thất bại → tăng bộ đếm
                attempts = cache.get(attempts_key, 0) + 1
                cache.set(attempts_key, attempts, LOCKOUT_SECONDS)

                remaining_attempts = MAX_ATTEMPTS - attempts
                if attempts >= MAX_ATTEMPTS:
                    cache.set(lockout_key, True, LOCKOUT_SECONDS)
                    messages.error(
                        request,
                        f'Đăng nhập sai quá {MAX_ATTEMPTS} lần. '
                        f'IP của bạn bị tạm khóa {LOCKOUT_MINUTES} phút.'
                    )
                else:
                    messages.error(
                        request,
                        f'Tên đăng nhập hoặc mật khẩu không đúng. '
                        f'Còn {remaining_attempts} lần thử.'
                    )

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'Bạn đã đăng xuất thành công.')
    return redirect('accounts:login')


def logout_view(request):
    logout(request)
    messages.info(request, 'Bạn đã đăng xuất thành công.')
    return redirect('accounts:login')


