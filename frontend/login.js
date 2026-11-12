const loginForm = document.querySelector('#loginForm');
const usernameInput = document.querySelector('#username');
const passwordInput = document.querySelector('#password');
const nextInput = document.querySelector('#nextInput');
const togglePasswordBtn = document.querySelector('#togglePasswordBtn');
const loginSubmitBtn = document.querySelector('#loginSubmitBtn');
const loginError = document.querySelector('#loginError');

function sanitizeNext(raw) {
  if (!raw || typeof raw !== 'string') return '/control';
  const trimmed = raw.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.startsWith('/\\')) {
    return '/control';
  }
  return trimmed;
}

const params = new URLSearchParams(window.location.search);
if (nextInput) {
  nextInput.value = sanitizeNext(params.get('next'));
}

function showError(message) {
  if (!loginError) return;
  loginError.textContent = message;
  loginError.classList.remove('hidden');
}

function clearError() {
  if (!loginError) return;
  loginError.textContent = '';
  loginError.classList.add('hidden');
  usernameInput?.removeAttribute('aria-invalid');
  passwordInput?.removeAttribute('aria-invalid');
}

const initialError = params.get('error');
if (initialError === 'invalid') {
  showError('Sai tên đăng nhập hoặc mật khẩu.');
  usernameInput?.setAttribute('aria-invalid', 'true');
  passwordInput?.setAttribute('aria-invalid', 'true');
} else if (initialError === 'ratelimit') {
  const retry = params.get('retry') || '60';
  showError(`Bạn đã thử sai quá nhiều lần. Vui lòng đợi ${retry} giây.`);
}

[usernameInput, passwordInput].forEach((input) => {
  input?.addEventListener('input', clearError);
});

if (togglePasswordBtn && passwordInput) {
  togglePasswordBtn.addEventListener('click', () => {
    const isHidden = passwordInput.type === 'password';
    passwordInput.type = isHidden ? 'text' : 'password';
    togglePasswordBtn.setAttribute('aria-pressed', String(isHidden));
    togglePasswordBtn.setAttribute('aria-label', isHidden ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
    togglePasswordBtn.textContent = isHidden ? '🙈' : '👁';
  });
}

if (loginForm) {
  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearError();

    if (!loginForm.reportValidity()) {
      return;
    }

    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    const next = sanitizeNext(nextInput?.value);

    loginSubmitBtn.disabled = true;
    loginSubmitBtn.textContent = 'Đang xác thực...';

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, next }),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showError(data.detail || 'Đăng nhập thất bại. Vui lòng thử lại.');
        usernameInput.setAttribute('aria-invalid', 'true');
        passwordInput.setAttribute('aria-invalid', 'true');
        passwordInput.focus();
        passwordInput.select();
        return;
      }

      window.location.assign(sanitizeNext(data.redirectTo || next));
    } catch (_err) {
      showError('Không kết nối được máy chủ. Vui lòng kiểm tra mạng và thử lại.');
    } finally {
      loginSubmitBtn.disabled = false;
      loginSubmitBtn.textContent = 'Đăng nhập';
    }
  });
}

