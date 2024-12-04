# admin_panel/dashboard/models.py

from django.db import models

class User(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    last_subject = models.CharField(max_length=255, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    start_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name or ''} (@{self.username or 'NoUsername'})"

class Message(models.Model):
    ROLE_CHOICES = (
        ('user', 'Пользователь'),
        ('bot', 'Бот'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role.capitalize()} в {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

class UserStatistic(models.Model):
    date = models.DateField(unique=True)
    user_count = models.IntegerField(default=0)
    command_count = models.IntegerField(default=0)
    message_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.date}: {self.user_count} новых пользователей, {self.command_count} команд, {self.message_count} сообщений"
