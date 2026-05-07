## Non_Contextual_Features

Requirements: 
- Papers (PDF)
- Appendex (PDF)
- Gemini API KEY
  
### Getting the gemini api key
To get started with the feature extraction, first get a Gemini API key, which can be found by creating an account at https://ai.google.dev/gemini-api/docs.

After getting the API, place it in second cell block where it says API_KEY = os.environ.get("GOOGLE_API_KEY", "INSERT_API_HERE")

### Running the code

Once the previous step is done, run all cells, then user input questions will pop up such as a Choose files button, which if you want to insert more than one paper, then you have to select multiple ones during one run of the code.

For each paper, the code will ask you if the paper has any appendix files, if no you can input no. 

If yes, you can upload the appendix seperately per every paper that is asked. 

After all inputs have been given. The code will start running and output a csv file of all the features extracted from the papers, to which you can download. 

## Contextual_Metadata

This section is purposed for extracting the contextual features.

Put the same Gemini API key that you got from the previous steps in the line below, 
client = genai.Client(api_key="Insert_Key_Here")

which falls under section "Estimation of social media usage"

Run all cellblocks and make sure you have all dependencies installed. 

Once running, you will be asked to answer some inputs, for example:

Enter country name: United States
Enter country ISO-2 code: US
Enter minimum year: 2024
Enter maximum year: 2027

Once answered, the cells will run and a csv file will be outputed, ou can combine both csv files to have a complete database.