import requests
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class AuthResult:
    """Результат авторизации"""
    success: bool
    session: Optional[requests.Session] = None
    user_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None


class MedscanAuthClient:
    """Клиент для авторизации в системе Medscan"""

    # Базовые заголовки
    BASE_HEADERS = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=1, i',
        'sec-ch-ua': '"Chromium";v="143", "Not A(Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'wr2-apirequest': '_',
        'x-integration-type': 'PORTAL-WR2',
    }

    # URL endpoints
    BASE_URL = "https://medscan-t.infoclinica.ru"
    LOGIN_URL = f"{BASE_URL}/login"
    LOGGED_IN_URL = f"{BASE_URL}/logged-in"
    DEPARTMENTS_URL = f"{BASE_URL}/pricelist/departments"

    def __init__(self, timeout: int = 30, verify_ssl: bool = True):
        """
        Инициализация клиента

        Args:
            timeout: Таймаут запросов в секундах
            verify_ssl: Проверять SSL сертификаты
        """
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def create_session(self) -> requests.Session:
        """Создает новую сессию с базовыми заголовками"""
        session = requests.Session()
        session.headers.update(self.BASE_HEADERS)
        session.verify = self.verify_ssl
        return session

    def get_initial_session(self, session: requests.Session) -> bool:
        """
        Получает начальную сессию (PLAY_SESSION)

        Args:
            session: Сессия requests

        Returns:
            bool: Успешно ли получена сессия
        """
        try:
            response = session.get(self.BASE_URL, timeout=self.timeout)
            response.raise_for_status()
            return 'PLAY_SESSION' in session.cookies
        except Exception as e:
            print(f"Ошибка получения начальной сессии: {e}")
            return False

    def check_auth_status(self, session: requests.Session) -> Dict[str, Any]:
        """
        Проверяет статус авторизации

        Args:
            session: Сессия requests

        Returns:
            Dict: Данные пользователя или пустой словарь
        """
        try:
            headers = {'referer': f'{self.BASE_URL}/'}
            response = session.get(
                self.LOGGED_IN_URL,
                headers=headers,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json() or {}
        except Exception as e:
            print(f"Ошибка проверки авторизации: {e}")
        return {}

    def build_login_data(self, username: str, password: str, boundary: str) -> bytes:
        """
        Строит multipart данные для авторизации

        Args:
            username: Логин пользователя
            password: Пароль пользователя
            boundary: Boundary для multipart

        Returns:
            bytes: Закодированные данные
        """
        body = f"""--{boundary}\r
Content-Disposition: form-data; name="username"\r
\r
{username}\r
--{boundary}\r
Content-Disposition: form-data; name="password"\r
\r
{password}\r
--{boundary}\r
Content-Disposition: form-data; name="formKey"\r
\r
pcode\r
--{boundary}\r
Content-Disposition: form-data; name="accept"\r
\r
false\r
--{boundary}\r
Content-Disposition: form-data; name="g-recaptcha-response"\r
\r
null\r
--{boundary}\r
Content-Disposition: form-data; name="captcha-value"\r
\r
\r
--{boundary}--\r
"""
        return body.encode('utf-8')

    def login(self, username: str, password: str) -> AuthResult:
        """
        Основная функция авторизации

        Args:
            username: Логин пользователя
            password: Пароль пользователя

        Returns:
            AuthResult: Результат авторизации
        """
        start_time = time.time()

        try:
            # 1. Создаем новую сессию
            session = self.create_session()

            # 2. Получаем начальную сессию
            print(f"[{username}] Получаем начальную сессию...")
            if not self.get_initial_session(session):
                return AuthResult(
                    success=False,
                    error_message="Не удалось получить начальную сессию"
                )

            # 3. Проверяем, что не авторизованы
            print(f"[{username}] Проверяем текущий статус...")
            auth_status = self.check_auth_status(session)
            if auth_status.get('authenticated'):
                return AuthResult(
                    success=True,
                    session=session,
                    user_data=auth_status,
                    cookies=dict(session.cookies)
                )

            # 4. Авторизуемся
            print(f"[{username}] Выполняем авторизацию...")
            boundary = "----WebKitFormBoundary4pcqHXyNzBGz7K3A"

            headers_login = {
                'content-type': f'multipart/form-data; boundary={boundary}',
                'origin': self.BASE_URL,
                'referer': f'{self.BASE_URL}/login',
            }

            login_data = self.build_login_data(username, password, boundary)

            response = session.post(
                self.LOGIN_URL,
                data=login_data,
                headers=headers_login,
                timeout=self.timeout
            )

            if response.status_code != 200:
                return AuthResult(
                    success=False,
                    error_message=f"Ошибка авторизации: HTTP {response.status_code}"
                )

            # 5. Проверяем успешность авторизации по ответу
            try:
                login_response = response.json()
                if not login_response.get('success', False):
                    return AuthResult(
                        success=False,
                        error_message="Авторизация не удалась по ответу сервера"
                    )
            except:
                # Если не JSON, считаем что что-то пошло не так
                return AuthResult(
                    success=False,
                    error_message="Неверный формат ответа от сервера"
                )

            # 6. Проверяем авторизацию через logged-in endpoint
            print(f"[{username}] Проверяем результат авторизации...")
            headers_logged = {'referer': f'{self.BASE_URL}/login'}

            response = session.get(
                self.LOGGED_IN_URL,
                headers=headers_logged,
                timeout=self.timeout
            )

            if response.status_code == 200:
                user_data = response.json()
                if user_data.get('authenticated'):
                    elapsed = time.time() - start_time
                    print(f"[{username}] ✓ Авторизация успешна за {elapsed:.2f} сек")

                    # Собираем все куки
                    cookies = {}
                    for cookie in session.cookies:
                        cookies[cookie.name] = cookie.value

                    return AuthResult(
                        success=True,
                        session=session,
                        user_data=user_data,
                        cookies=cookies,
                        error_message=None
                    )
                else:
                    return AuthResult(
                        success=False,
                        error_message="Пользователь не авторизован после логина"
                    )
            else:
                return AuthResult(
                    success=False,
                    error_message=f"Ошибка проверки авторизации: HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            return AuthResult(
                success=False,
                error_message="Таймаут при выполнении запроса"
            )
        except requests.exceptions.ConnectionError:
            return AuthResult(
                success=False,
                error_message="Ошибка соединения"
            )
        except Exception as e:
            return AuthResult(
                success=False,
                error_message=f"Неизвестная ошибка: {str(e)}"
            )

def authorize_user(username: str, password: str) -> Dict[str, Any]:
    """
    Основная функция авторизации пользователя

    Args:
        username: Логин пользователя
        password: Пароль пользователя
        test_access: Тестировать доступ к защищенному ресурсу

    Returns:
        Dict: Результат авторизации
    """
    client = MedscanAuthClient()

    print(f"Начинаем авторизацию пользователя: {username}")
    result = client.login(username, password)

    response_data = {
        "success": result.success,
        "username": username,
        "error": result.error_message,
        "timestamp": time.time(),
    }
    if result.success:
        response_data.update({
            "user_id": result.user_data.get('id'),
            "full_name": result.user_data.get('fullName'),
            "email": result.user_data.get('email'),
            "phone": result.user_data.get('phone'),
            "authenticated": result.user_data.get('authenticated'),
            "check_token": result.user_data.get('checkToken'),
            "cookies_obtained": list(result.cookies.keys()) if result.cookies else [],
            "session": result.session,
        })

    return response_data


# def main():
#     """Пример использования модуля авторизации"""
#     user = {"username": "atwhatilold@gmail.com", "password": "ilikewow"}
#
#     result = authorize_user(
#         username=user['username'],
#         password=user['password'],
#     )
#
#     print(result)
#
#     # Данные для записи
#     reserve_data = {
#         # todo: все эти данные берем из ответа на https://medscan-t.infoclinica.ru/api/reservation/schedule
#         "date": "20260124",
#         "dcode": 990102079,
#
#         # todo: тут ставим st + 30 минут (то есть запись длится 30 минут)
#         "en": "21:00",
#         "filial": 4,
#         "onlineType": 0,
#         "schedident": 40075624,
#
#         # todo: сюда ставим время.Нужно проверить что запись на этот день свободна.
#         #  если "isFree": false, то запись невозможна в этот день и надо искать другую.
#         "st": "11:00",
#         "depnum": 990034235
#     }
#
#     # Заголовки для запроса записи
#     headers = {
#         'accept': 'application/json, text/plain, */*',
#         'accept-language': 'en-US,en;q=0.9',
#         'priority': 'u=1, i',
#         'referer': 'https://medscan-t.infoclinica.ru/reservation',
#         'sec-ch-ua': '"Chromium";v="143", "Not A(Brand";v="24"',
#         'sec-ch-ua-mobile': '?0',
#         'sec-ch-ua-platform': '"Linux"',
#         'sec-fetch-dest': 'empty',
#         'sec-fetch-mode': 'cors',
#         'sec-fetch-site': 'same-origin',
#         'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
#         'wr2-apirequest': '_',
#         'x-integration-type': 'PORTAL-WR2',
#         'content-type': 'application/json',
#     }
#
#     session = result['session']
#
#     # Устанавливаем заголовки в сессию
#     session.headers.update(headers)
#
#     # Отправляем запрос на запись
#     response = session.post(
#         'https://medscan-t.infoclinica.ru/api/reservation/reserve',
#         json=reserve_data
#     )
#
#     # response = session.delete(
#     #     'https://medscan-t.infoclinica.ru/record/delete/40465891/4',
#     #     json=reserve_data
#     # )
#     print(f"Статус записи: {response.status_code}")
#     print(f"Ответ: {response.text}")
#
# if __name__ == "__main__":
#     main()

