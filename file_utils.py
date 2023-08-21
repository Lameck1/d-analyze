import io
import magic
import chardet

ALLOWED_MIME_TYPES = {'text/csv'}

def allowed_file(file):
    """
    This function checks if the uploaded file is allowed. It checks if the file has a CSV extension,
    and tries to decode the file using all available encodings.

    Parameters:
        file (FileStorage): The file to be checked.

    Returns:
        bool: True if the file is a valid CSV, False otherwise.
    """

    file_extension = file.filename.rsplit('.', 1)[1].lower()
    file_blob = file.read()
    file.seek(0)  # reset file pointer to the beginning

    # Check if the file has a CSV extension
    if file_extension == 'csv':
        # Detect the file encoding
        detected_encoding = chardet.detect(file_blob)['encoding']

        try:
            file_blob.decode(detected_encoding)
            return True  # file is valid CSV
        except UnicodeDecodeError:
            pass

    # For non-CSV files, you can check MIME types
    mime_type = magic.from_buffer(file_blob, mime=True)
    if mime_type in ALLOWED_MIME_TYPES:
        return True

    return False  # file is not valid CSV
