\# PLAN



\## 1. User and consumption

The user is the research analyst. The pipeline produces validated, evidence-linked JSON records that a downstream system (a database behind an API, review UI or chatbot) serves to analysts. Records are extracted once and queried many times.



\## 2. Product surface

Version one is a batch pipeline run per report, producing one JSON file. Review UI, query API or chatbot, and alerting build on the same records later.



\## 3. Optimisation target

Coverage first, then correctness, then cost. A missed principal risk is invisible to an analyst, whereas an extra candidate is visible and removable, so recall is favoured when locating risks. Faithfulness is a floor, not a trade: no field is accepted unless it is traceable to source text and page.



\## 4. Assumptions

\- One report, one fiscal year, English, text-based PDF.

\- A principal risk is a risk to the company that the report itself presents as main or material. Items the report scores as immaterial, opportunities, and impacts on people and the environment are out of scope for this slice.

\- Mitigation is only what the report states; otherwise "not stated".

\- Categories come from a fixed, versioned list stored on every record. New specifics are captured as open tags, and risks that do not fit go to "other" for periodic review.

\- Processing is a batch job; latency is not critical because no user waits on it.

\- A small local model on CPU stands in for a production model; the model is a configuration setting.





