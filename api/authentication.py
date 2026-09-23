"""JWT-Anmeldung der App mit Widerruf bei Passwortwechsel.

SimpleJWT-Tokens lassen sich ohne Blacklist-Tabelle nicht zurückziehen: ein
gestohlenes Handy blieb bis zu 30 Tage angemeldet, auch nach einem neuen
Passwort. Deshalb tragen die Tokens einen Fingerabdruck des Passwort-Hashes
(wie Django ihn für Web-Sessions nutzt). Ändert sich das Passwort – oder wird
das Konto gelöscht –, passen alle alten Tokens nicht mehr.

Tokens aus der Zeit vor dieser Umstellung haben den Fingerabdruck noch nicht;
sie werden bis zu ihrem Ablauf akzeptiert und bekommen ihn beim nächsten
Refresh, damit niemand beim Update abgemeldet wird.
"""
from django.contrib.auth import get_user_model
from rest_framework import exceptions as drf_exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

PASSWORD_CLAIM = "pwh"


def password_fingerprint(user):
    return user.get_session_auth_hash()[:20]


def tokens_for_user(user):
    """Neues Token-Paar, z. B. nach einem Passwortwechsel für das eigene Gerät."""
    refresh = RefreshToken.for_user(user)
    refresh[PASSWORD_CLAIM] = password_fingerprint(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class WochiiTokenObtainPairSerializer(TokenObtainPairSerializer):
    """App-Login mit derselben Sperre gegen Passwort-Raten wie im Web."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token[PASSWORD_CLAIM] = password_fingerprint(user)
        return token

    def validate(self, attrs):
        from accounts.utils import login_blocked, record_failed_login

        request = self.context.get("request")
        username = attrs.get(self.username_field)
        if request is not None and username and login_blocked(request, username):
            raise AuthenticationFailed(
                "Zu viele Fehlversuche. Bitte warte 15 Minuten.", "too_many_attempts"
            )
        try:
            return super().validate(attrs)
        except drf_exceptions.AuthenticationFailed:
            # SimpleJWT wirft die DRF-Klasse, nicht seine eigene Unterklasse.
            if request is not None and username:
                record_failed_login(request, username)
            raise


class WochiiTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not api_settings.USER_AUTHENTICATION_RULE(user):
            raise AuthenticationFailed("Kein aktives Konto für dieses Token.", "no_active_account")
        claim = refresh.payload.get(PASSWORD_CLAIM)
        if claim is not None and claim != password_fingerprint(user):
            raise InvalidToken("Das Passwort wurde geändert. Bitte neu anmelden.")

        data = {"access": str(refresh.access_token)}
        if claim is None:
            # Token von vor der Umstellung: weiter gültig bis zu seinem
            # Ablaufdatum, aber nicht rotieren – sonst würde ein gestohlenes
            # Alt-Token nach einem Passwortwechsel zu einem neuen, gültigen
            # Token „aufgewertet“.
            return data
        if api_settings.ROTATE_REFRESH_TOKENS:
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            data["refresh"] = str(refresh)
        return data


class WochiiJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        claim = validated_token.get(PASSWORD_CLAIM)
        if claim is not None and claim != password_fingerprint(user):
            raise InvalidToken("Das Passwort wurde geändert. Bitte neu anmelden.")
        return user
