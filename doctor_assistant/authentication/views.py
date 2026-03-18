from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from .forms import RegistrationForm

def register(request):
	if request.method == 'POST':
		form = RegistrationForm(request.POST)
		if form.is_valid():
			form.save()
			messages.success(request, "Account created successfully!")
			return redirect('authentication:login')

	else:
		form = RegistrationForm()  # Only create a blank form if GET request

	return render(request, 'register.html', {"form": form})

def login_view(request):
	if request.method == 'POST':
		username = request.POST['username']
		password = request.POST['password']

		user = authenticate(request=request, username=username, password=password)

		if user is not None:
			login(request, user)
			return redirect('/app/')
		else:
			messages.error(request, "Invalid Username or Password")

	return render(request, 'login.html')

def logout_view(request):
	logout(request)
	return redirect('authentication:login')
