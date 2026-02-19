import google.generativeai as genai

genai.configure(api_key="AIzaSyCVYRz26YhBqG0ho8UqMuAU0mSiWYAhkwc")

for model in genai.list_models():
    if "generateContent" in model.supported_generation_methods:
        print(model.name)
