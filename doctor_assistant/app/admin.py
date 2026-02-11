from django.contrib import admin
from .models import Interview
from django.utils.html import format_html
import json

@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = ('patient_id', 'interview_type', 'doctor', 'created_at')  # removed status
    list_filter = ('interview_type',)  # only filter by interview_type
    search_fields = ('patient_id', 'doctor__username')
    readonly_fields = ('hpc_json_pretty', 'transcript')

    def hpc_json_pretty(self, obj):
        if obj.hpc_json:
            pretty = json.dumps(obj.hpc_json, indent=2)
            return format_html("<pre>{}</pre>", pretty)
        return "-"
    hpc_json_pretty.short_description = "HPC JSON"