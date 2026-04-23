# 本文档无法处理，具有logical或者sequencical logic的问题

import streamlit as st
from openai import AzureOpenAI
from openai import OpenAI
import tiktoken
import os
import json
import sqlite3
from sqlite3 import Error
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

# Initialize the Azure OpenAI client
# client = AzureOpenAI(
#     azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
#     api_key=os.getenv("AZURE_OPENAI_API_KEY"),
#     api_version=os.getenv("AZURE_OPENAI_API_VERSION")
# )
client = OpenAI(
    base_url="https://"+os.getenv("FOUNDRY_PROJECT_RESOURCE")+".openai.azure.com/openai/v1/",
    api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
)

# Define the database file
db_file = "data/fb.sqlite"

def create_connection():
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

    return conn

#'columns': ['imdb_id', 'title', 'year', 'mpaa_rating', 'running_time', 'genres', 'budget', 'opening_wkd', 'gross_ww', 'gross_us', 'awards', 'summary', 'country', 'language', 'page_username']
# function to add a new movie to the imdb_movie_overview table
def add_movie(imdb_id, title, year, mpaa_rating, running_time, genres, budget, opening_wkd, gross_ww, gross_us, awards, summary, country, language, page_username):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO imdb_movie_overview (imdb_id, title, year, mpaa_rating, running_time, genres, budget, opening_wkd, gross_ww, gross_us, awards, summary, country, language, page_username) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (imdb_id, title, year, mpaa_rating, running_time, genres, budget, opening_wkd, gross_ww, gross_us, awards,
             summary, country, language, page_username))
        conn.commit()
        if cur.rowcount > 0:
            print(f"Added movie {title} to the database")
            return f"Added movie {title} to the database"
        else:
            print(f"Failed to add movie {title} to the database")
            return f"Failed to add movie {title} to the database"
    except Error as e:
        print(f"Failed to add movie {title} to the database: {e}")
        return f"Failed to add movie {title} to the database"
    finally:
        cur.close()
        conn.close()

# delete a movie from the imdb_movie_overview table
def delete_movie(imdb_id):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM imdb_movie_overview WHERE imdb_id=?", (imdb_id,))
        conn.commit()
        if cur.rowcount > 0:
            print(f"Deleted movie with IMDb ID {imdb_id} from the database")
            return f"Deleted movie with IMDb ID {imdb_id} from the database"
        else:
            print(f"Failed to delete movie with IMDb ID {imdb_id} from the database")
            return f"Failed to delete movie with IMDb ID {imdb_id} from the database"
    except Error as e:
        print(f"Failed to delete movie with IMDb ID {imdb_id} from the database: {e}")
        return f"Failed to delete movie with IMDb ID {imdb_id} from the database"
    finally:
        cur.close()
        conn.close()

def get_imdb_id_by_title(title):
    """
    Query IMDb ID by movie title
    :param title:
    :return:
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        stop_words = {"a", "an", "the", "and", "or", "but", "if", "to", "of", "in", "on", "for", "with", "as", "by", "at"}
        words = [word for word in title.split() if word.lower() not in stop_words]
        query = "SELECT title,imdb_id FROM imdb_movie_overview WHERE " + " OR ".join(["title LIKE ?" for _ in words])
        cur.execute(query, tuple(f"%{word}%" for word in words))
        rows = cur.fetchall()
        column_names = [description[0] for description in cur.description]
        print({"columns": column_names, "rows": rows})
        return {"columns": column_names, "rows": rows}
    except Error as e:
        print(f"Error querying IMDb ID by title: {e}")
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()

def get_movie_overview(imdb_id):
    """
    Query movie overview by imdb_id
    :param imdb_id:
    :return:
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM imdb_movie_overview WHERE imdb_id=?", (imdb_id,))
        rows = cur.fetchall()
        column_names = [description[0] for description in cur.description]
        print({"columns": column_names, "rows": rows})
        return {"columns": column_names, "rows": rows}
    except Error as e:
        print(f"Error querying movie overview: {e}")
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()

def get_boxoffice(imdb_id):
    """
    Query box office by imdb_id
    :param imdb_id:
    :return:
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM boxoffice WHERE imdb_id=? order by date asc limit 12", (imdb_id,))
        rows = cur.fetchall()
        column_names = [description[0] for description in cur.description]
        print({"columns": column_names, "rows": rows})
        return {"columns": column_names, "rows": rows}
    except Error as e:
        print(f"Error querying box office: {e}")
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()

def get_fbposts(imdb_id):
    """
    Query Facebook posts by imdb_id
    :param imdb_id:
    :return:
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM fbposts WHERE imdb_id=? order by random() limit 10", (imdb_id,))
        rows = cur.fetchall()
        column_names = [description[0] for description in cur.description]
        print({"columns": column_names, "rows": rows})
        return {"columns": column_names, "rows": rows}
    except Error as e:
        print(f"Error querying Facebook posts: {e}")
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()

def get_fandango_reviews(imdb_id):
    """
    Query Fandango reviews by imdb_id
    :param imdb_id:
    :return:
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM fandango_review WHERE imdb_id=? order by random() limit 10", (imdb_id,))
        rows = cur.fetchall()
        column_names = [description[0] for description in cur.description]
        print({"columns": column_names, "rows": rows})
        return {"columns": column_names, "rows": rows}
    except Error as e:
        print(f"Error querying Fandango reviews: {e}")
        return {"error": str(e)}
    finally:
        cur.close()
        conn.close()


def run_conversation(user_input):
    messages = [{"role": "system", "content": "You are a helpful assistant who knows a lot about movies, box office revenue, Facebook posts, and Fandango reviews."}]
    messages.append({"role": "user", "content": user_input})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "add_movie",
                "description": "Add a new movie record to the database table",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                        "title": {
                            "type": "string",
                            "description": "The title of the movie",
                        },
                        "year": {
                            "type": "integer",
                            "description": "The year the movie was released",
                        },
                        "mpaa_rating": {
                            "type": "string",
                            "description": "The MPAA rating of the movie",
                        },
                        "running_time": {
                            "type": "integer",
                            "description": "The running time of the movie in minutes",
                        },
                        "genres": {
                            "type": "string",
                            "description": "The genres of the movie",
                        },
                        "budget": {
                            "type": "integer",
                            "description": "The budget of the movie",
                        },
                        "opening_wkd": {
                            "type": "integer",
                            "description": "The opening weekend box office revenue",
                        },
                        "gross_ww": {
                            "type": "integer",
                            "description": "The worldwide box office revenue",
                        },
                        "gross_us": {
                            "type": "integer",
                            "description": "The domestic box office revenue",
                        },
                        "awards": {
                            "type": "string",
                            "description": "The awards the movie has won",
                        },
                        "summary": {
                            "type": "string",
                            "description": "A summary of the movie",

                        },
                        "country": {
                            "type": "string",
                            "description": "The country where the movie was produced",
                        },
                        "language": {
                            "type": "string",
                            "description": "The language of the movie",
                        },
                        "page_username": {
                            "type": "string",
                            "description": "The Facebook page username of the movie",
                        },
                    },
                    "required": ["imdb_id", "title"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_movie",
                "description": "Delete a movie record from the database table imdb_movie_overview by IMDb ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                    },
                    "required": ["imdb_id"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_imdb_id_by_title",
                "description": "Get IMDb ID by movie title",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "The title of the movie"},
                    },
                    "required": ["title"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_movie_overview",
                "description": """Get movie information by IMDb ID. The IMDb ID is a unique identifier for movies on IMDb.
                                Movie information includes the title, year, MPAA rating, running time, genres, budget, opening weekend box office revenue, worldwide box office revenue, domestic box office revenue, awards, summary, country, language, and Facebook page username.
                                """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                    },
                    "required": ["imdb_id"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_boxoffice",
                "description": "Get box office revenue by IMDb ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                    },
                    "required": ["imdb_id"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_fbposts",
                "description": "Get Facebook posts by IMDb ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                    },
                    "required": ["imdb_id"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_fandango_reviews",
                "description": "Get Fandango reviews by IMDb ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "imdb_id": {
                            "type": "string",
                            "description": "The IMDb ID of the movie",
                        },
                    },
                    "required": ["imdb_id"],
                },
            }
        }
    ]

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )

    response_message = response.choices[0].message
    messages.append(response_message)
    print("Model's response:")
    print(response_message)

    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"Function call: {function_name}")
            print(f"Function arguments: {function_args}")
            if function_name == "get_movie_overview":
                function_response = get_movie_overview(imdb_id=function_args.get("imdb_id"))
            elif function_name == "get_boxoffice":
                function_response = get_boxoffice(imdb_id=function_args.get("imdb_id"))
            elif function_name == "get_fbposts":
                function_response = get_fbposts(imdb_id=function_args.get("imdb_id"))
            elif function_name == "get_fandango_reviews":
                function_response = get_fandango_reviews(imdb_id=function_args.get("imdb_id"))
            elif function_name == "get_imdb_id_by_title":
                function_response = get_imdb_id_by_title(title=function_args.get("title"))
            elif function_name == "add_movie":
                function_response = add_movie(**function_args)
            elif function_name == "delete_movie":
                function_response = delete_movie(imdb_id=function_args.get("imdb_id"))
            else:
                function_response = {"error": "Unknown function"}

            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": json.dumps(function_response),
            })

    final_response = client.chat.completions.create(
        model=os.getenv("FOUNDTRY_PROJECT_DEPLOYMENT"),
        messages=messages,
    )
    return final_response.choices[0].message.content


def chatbot():
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    st.title("Chatbot")
    user_input = st.text_input("You: ", key="user_input")

    if st.button("Send"):
        st.session_state.messages.append({"role": "user", "content": user_input})
        bot_response = run_conversation(user_input)
        st.session_state.messages.append({"role": "assistant", "content": bot_response})


    for message in st.session_state.messages:
        if message["role"] == "user":
            st.write(f"You: {message['content']}")
        elif message["role"] == "assistant":
            st.write(f"Bot: {message['content']}")

if __name__ == "__main__":
    chatbot()