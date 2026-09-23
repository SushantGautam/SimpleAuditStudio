from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Project, ProjectMembership, User


@admin.register(User)
class SimpleAuditUserAdmin(UserAdmin):
    pass


class ProjectMembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProjectMembershipInline]


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "role", "created_at")
    list_filter = ("role", "project")
    search_fields = ("user__username", "project__name")
