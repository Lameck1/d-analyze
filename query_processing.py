import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import openai

# Download necessary resources
nltk.download('punkt')
nltk.download('stopwords')

def process_user_input(user_question):
    # Tokenize the question
    tokens = word_tokenize(user_question)
    
    # Remove stop words
    stop_words = set(stopwords.words('english'))
    keywords = [word for word in tokens if word.lower() not in stop_words]
    
    # You may add more processing here, like stemming or lemmatizing
    
    return keywords


def check_query_relevance(user_query, dataset_context):
    # Constructing a relevance prompt
    prompt = f"How relevant is the question '{user_query}' to the dataset context '{dataset_context}'?"

    # Calling the OpenAI API
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        max_tokens=50
    )

    # Extracting the numerical relevance score
    relevance_score = extract_numerical_value(response.choices[0].text)

    return relevance_score

