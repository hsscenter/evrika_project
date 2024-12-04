# admin_panel/dashboard/admin.py

from django.contrib import admin
from .models import User, Message, UserStatistic
from django.urls import path
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from datetime import datetime

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'telegram_id', 'username', 'first_name', 'last_subject', 'is_paid', 'is_banned', 'start_date')
    search_fields = ('telegram_id', 'username', 'first_name', 'last_name')
    list_filter = ('is_paid', 'is_banned', 'start_date')
    actions = ['ban_users', 'unban_users', 'make_paid', 'make_free']

    def ban_users(self, request, queryset):
        queryset.update(is_banned=True)
    ban_users.short_description = "Заблокировать выбранных пользователей"

    def unban_users(self, request, queryset):
        queryset.update(is_banned=False)
    unban_users.short_description = "Разблокировать выбранных пользователей"

    def make_paid(self, request, queryset):
        queryset.update(is_paid=True)
    make_paid.short_description = "Отметить выбранных пользователей как оплаченных"

    def make_free(self, request, queryset):
        queryset.update(is_paid=False)
    make_free.short_description = "Отметить выбранных пользователей как неоплаченных"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'role', 'timestamp')
    search_fields = ('user__telegram_id', 'user__username', 'content')
    list_filter = ('role', 'timestamp')

@admin.register(UserStatistic)
class UserStatisticAdmin(admin.ModelAdmin):
    list_display = ('date', 'user_count', 'command_count', 'message_count')
    search_fields = ('date',)

# Создание пользовательского AdminSite для статистики
class DashboardAdminSite(admin.AdminSite):
    site_header = 'Evrika Административная Панель'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('statistics/', self.admin_view(self.statistics_view), name='statistics'),
        ]
        return custom_urls + urls

    def statistics_view(self, request):
        if not request.user.is_superuser:
            self.message_user(request, "У вас нет доступа к этой странице.")
            return redirect('admin:index')

        total_users = User.objects.count()
        today = timezone.now().date()
        today_new_users = User.objects.filter(start_date__date=today).count()
        total_commands = UserStatistic.objects.aggregate(models.Sum('command_count'))['command_count__sum'] or 0
        total_messages = UserStatistic.objects.aggregate(models.Sum('message_count'))['message_count__sum'] or 0
        user_stats = UserStatistic.objects.all().order_by('date')

        context = dict(
            self.each_context(request),
            total_users=total_users,
            today_new_users=today_new_users,
            total_commands=total_commands,
            total_messages=total_messages,
            user_stats=user_stats,
        )
        return TemplateResponse(request, "admin/statistics.html", context)

admin_site = DashboardAdminSite(name='dashboard')

# Регистрируем модели в новом AdminSite
admin_site.register(User, UserAdmin)
admin_site.register(Message, MessageAdmin)
admin_site.register(UserStatistic, UserStatisticAdmin)
