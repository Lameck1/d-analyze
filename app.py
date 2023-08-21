import json
from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from database import get_db, close_db, execute_query
import logging
import os
from io import BytesIO
import numpy as np
import pandas as pd
import requests
from datetime import datetime, date
from json import JSONEncoder as BaseJSONEncoder
from pandas._libs.tslibs.nattype import NaTType
from file_utils import allowed_file
from data_cleaning import clean_and_store_data
from data_processing import get_sql_query, get_assistant_response, generate_charts

logging.basicConfig(filename='/tmp/app.log', level=logging.DEBUG)

def filter_resources(data):
    # Check if there's any result
    if 'result' not in data:
        return data

    filtered_results = []
    for package in data['result']['results']:
        if any(resource['format'].lower() in ['csv'] for resource in package['resources']):
            filtered_results.append(package)

    data['result']['results'] = filtered_results
    return data

class JSONEncoder(BaseJSONEncoder):
    def default(self, obj):
        if isinstance(obj, NaTType):
            return None
        elif isinstance(obj, np.generic):
            if np.isnan(obj):
                return None
            return obj.item()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self.default(value) for key, value in obj.items()}
        return super().default(obj)

app = Flask(__name__)
app.json_encoder = JSONEncoder

@app.before_request
def before_request():
    get_db()

@app.teardown_request
def teardown_request(exception):
    close_db(exception)

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    This function is a Flask route that handles POST requests to upload a file. 
    The file is expected to be part of the request's files under the key 'file'.
    
    The function performs several checks to ensure the file is present, has a valid filename, 
    and is of an allowed type. If these checks pass, the file is saved to a temporary location 
    and then processed by the `clean_and_store_data` function. 
    
    If the file is successfully processed, the function returns a JSON response containing the 
    upload ID and the names of the columns in the uploaded data. If any errors occur during 
    this process, they are logged and an appropriate error message is returned in the JSON response.
    
    Parameters:
    None. The function expects a file to be part of the Flask request's files.
    
    Returns:
    flask.Response: A Flask Response object containing a JSON response. The JSON response 
    includes the upload ID and column names if the file was successfully processed, or an 
    error message if an error occurred.
    """
    try:
        if 'file' not in request.files:
            logging.error("No file part in the request")
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']
        if file.filename == '':
            logging.error("No selected file")
            return jsonify({'error': 'No selected file'}), 400

        if file and allowed_file(file):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            try:
                file.save(file_path)
                conn = get_db()
                upload_id, sample_data = clean_and_store_data(file_path, file, conn)

            except Exception as e:
                logging.error(f"Error saving file: {str(e)}", exc_info=True)
                return jsonify({'error': f'Error saving file: {str(e)}'}), 500
            finally:
                os.remove(file_path) 

            if upload_id is not None and not sample_data.empty:
                json_sample_data = sample_data.to_json(orient='records', date_format='iso', default_handler=JSONEncoder().default)
                response_data = {
                    'upload_id': upload_id, 
                    'sample_data': json.loads(json_sample_data) # Parse the JSON string to a Python object
                }
                return Response(json.dumps(response_data), content_type='application/json'), 200
            else:
                logging.error("Error processing file")
                return jsonify({'error': 'Error processing file'}), 400
        else:
            logging.error("Unsupported file type")
            return jsonify({'error': 'Unsupported file type'}), 400
    except Exception as e:
        logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({'error': f'Unhandled exception: {str(e)}'}), 500
    
@app.route('/analyze_data/<upload_id>', methods=['POST'])
def analyze_data_endpoint(upload_id):
    """
    This function is a Flask route that handles POST requests to analyze data.
    It uses the other functions defined above to generate an SQL query based on the user's question, execute the query, generate a human-friendly response, and create a chart.
    
    Parameters:
    upload_id (str): The ID of the data upload to analyze.
    
    Returns:
    flask.Response: A Flask Response object containing a JSON response to the client.
    """
    try:
        payload = request.get_json()
        user_query = payload.get('query')

        if not user_query:
            return jsonify({'error': 'No query provided'}), 400

        cursor = get_db().cursor()

        # Get column names from the database
        cursor.execute(f"DESCRIBE {upload_id};")
        columns = cursor.fetchall()
        column_names = ', '.join([column[0] for column in columns])

        print(column_names)

        cleaned_sql_query = get_sql_query(user_query, column_names, upload_id)

        print(cleaned_sql_query)

        messages = []
        if cleaned_sql_query:
            # Execute the SQL query and get the results
            query_results = execute_query(cleaned_sql_query)

            assistant_response = get_assistant_response(user_query, cleaned_sql_query, query_results)
            messages.append({"role": "assistant", "content": f"{assistant_response}"})

            # create chart from query_results if possible and append to messages
            chart_string = generate_charts(query_results)
            if chart_string:
                messages.append({"role": "chart", "content": chart_string})

            return jsonify({"messages": messages})
        else:
            messages.append({"role": "assistant", "content": f"Could not generate an SQL query from the user's question: {user_query}"})
            return jsonify({"messages": messages})
    except Exception as e:
        logging.error(f"Error analyzing data: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error analyzing data: {str(e)}'}), 500

@app.route('/search', methods=['POST'])
def search():
    try:
        payload = request.get_json()
        query = payload.get('query')
        if not query:
            return jsonify({'error': 'No query provided'}), 400

        url = f'https://data.humdata.org/api/3/action/package_search?q={query}'
        response = requests.get(url)
        data = response.json()
        filtered_data = filter_resources(data)
        return jsonify(filtered_data), 200

    except Exception as e:
        logging.error(f"Error in search: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error in search: {str(e)}'}), 500

@app.route('/upload_from_url', methods=['POST'])
def upload_from_url():
    try:
        url = request.json.get('url', '')

        # Send a request to the URL
        r = requests.get(url, allow_redirects=True)
        if r.status_code != 200:
            return jsonify({'error': f'Error downloading file from {url}'}), 500

        # Create a FileStorage instance for the downloaded file
        file = FileStorage(
            stream=BytesIO(r.content),
            filename=url.split("/")[-1],  # Use the last part of the URL as the filename
            content_type=r.headers['content-type']
        )

        if file and allowed_file(file):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)  # Save the file to the upload folder
            conn = get_db()

            upload_id, sample_data = clean_and_store_data(file_path, file, conn)
            
            if upload_id is not None and not sample_data.empty:
                json_sample_data = sample_data.to_json(orient='records', date_format='iso', default_handler=JSONEncoder().default)
                response_data = {
                    'upload_id': upload_id, 
                    'sample_data': json.loads(json_sample_data) # Parse the JSON string to a Python object
                }
                return Response(json.dumps(response_data), content_type='application/json'), 200
            else:
                logging.error("Error processing file")
                return jsonify({'error': 'Error processing file'}), 400
        else:
            logging.error("Unsupported file type")
            return jsonify({'error': 'Unsupported file type'}), 400

    except Exception as e:
        logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({'error': f'Unhandled exception: {str(e)}'}), 500
    
