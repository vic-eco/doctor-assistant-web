from django.db import models

# Create your models here.

from django.db import models
from django.contrib.auth.models import User


class Interview(models.Model):

    NEW = "new"
    EXISTING = "existing"

    TYPE_CHOICES = [
        (NEW, "New Patient"),
        (EXISTING, "Existing Patient"),
    ]

    doctor = models.ForeignKey(User, on_delete=models.CASCADE)

    patient_id = models.CharField(max_length=100)
    interview_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    transcript = models.TextField(blank=True)

    hpc_json = models.JSONField(null=True, blank=True)   # 🔥 perfect for this

    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.patient_id} ({self.interview_type})"
