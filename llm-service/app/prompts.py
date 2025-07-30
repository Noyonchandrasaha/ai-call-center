def generate_system_prompt(request) -> str:
    """Generate system prompt based on the request context"""
    org_id = request.org_id
    stage = request.conversation_stage
    lead_question = request.lead_question
    remaining_questions = request.remaining_questions
    documents = request.documents
    
    # Base role definition
    prompt = f"""
    You are a customer service AI assistant for organization: {org_id}.
    You are currently in the {stage} stage of the conversation.
    Respond helpfully, professionally, and concisely.
    """
    
    # Add document context if available
    if documents:
        prompt += "\n\nRelevant information from knowledge base:\n"
        for doc in documents[:3]:  # Limit to 3 most relevant documents
            prompt += f"- {doc.title}: {doc.content[:200]}...\n"
    
    # Add lead question instructions
    if lead_question:
        prompt += f"""
        \nThe user needs to answer this question: "{lead_question.question_text}"
        Your response should naturally guide them to answer this question.
        Capture their response in the format: [ANSWER: their response]
        """
    
    # Add pending questions context
    if remaining_questions:
        prompt += f"""
        \nYou still need to ask these required questions: {", ".join(remaining_questions)}
        """
    
    # Add transfer instructions
    prompt += """
    \nIf the user requests to speak to a human agent or if you cannot resolve their issue:
    - Respond that you'll transfer them to a human agent
    - Add [TRANSFER] to the end of your response
    """
    
    # Add response formatting rules
    prompt += """
    \nResponse Guidelines:
    - Keep responses under 3 sentences
    - Use simple, clear language
    - Avoid technical jargon
    - Maintain a friendly, professional tone
    - End questions with a question mark
    - Never make up information
    """
    
    return prompt.strip()