from google import genai

client = genai.Client()
print(
    client.models.generate_content(model="gemini-3.8-flash", contents="Sag Hallo").text
)
