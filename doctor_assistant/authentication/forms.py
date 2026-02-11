from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class RegistrationForm(UserCreationForm):
	password1 = forms.CharField(
		label="Password",
		widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
	)
	password2 = forms.CharField(
		label="Confirm Password",
		widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
	)
        
	class Meta:
		model = User
		fields = ['username', 'password1', 'password2']
		widgets = {
			'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
		}
