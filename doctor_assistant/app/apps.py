from django.apps import AppConfig
from .llm_loader import get_llm


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        get_llm()