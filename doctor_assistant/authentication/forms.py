from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class RegistrationForm(UserCreationForm):
	email = forms.EmailField(
		widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'})
	)

	first_name = forms.CharField(
		widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
	)

	last_name = forms.CharField(
		max_length=255,
		widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
	)

	password1 = forms.CharField(
		widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
	)

	password2 = forms.CharField(
		widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
	)

	class Meta:
		model = User
		fields = ['first_name','last_name','email', 'password1', 'password2']

