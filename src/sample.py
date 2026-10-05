from pii_anonymizer import anonymize_data

data = {
    "Customer_ID": 1001,
    "Name": "Mohamed Fateen",
    "Email": "mohamed@gmail.com",
    "Phone": "9876543210",
    "PAN": "ABCDE1234F",
    "Aadhaar": "1234 5678 9012",
    "City": "Chennai",
}

result = anonymize_data(data)

print(result)