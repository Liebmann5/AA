% form_semantics.lp
% This file defines the pure logic of a job application form.

% --- DEFINITIONS ---
% We define synonyms for common fields so our rules are robust.

is_synonym(first_name, "first name").
is_synonym(first_name, "given name").
is_synonym(first_name, "forename").

is_synonym(resume, "resume").
is_synonym(resume, "cv").
is_synonym(resume, "upload resume").

is_synonym(submit, "submit").
is_synonym(submit, "apply").
is_synonym(submit, "submit application").
is_synonym(submit, "next").

% --- RULES ---
% A node is a target for a specific field IF its role matches AND its name matches a synonym.

% Rule: Find the First Name text box
target(first_name, NodeID) :- 
    node(NodeID, "textbox", Name), 
    is_synonym(first_name, Name).

% Rule: Find the Resume upload button
target(resume_upload, NodeID) :- 
    node(NodeID, "button", Name), 
    is_synonym(resume, Name).

% Rule: Find the Submit/Next button
target(submit_button, NodeID) :- 
    node(NodeID, "button", Name), 
    is_synonym(submit, Name).

% Rule: Find Checkboxes (e.g., Terms of Service)
% We target any checkbox that mentions "agree" or "terms"
target(tos_checkbox, NodeID) :-
    node(NodeID, "checkbox", Name),
    Name != "", % Must have a name
    #match(".*(agree|terms).*", Name). % Regex match built into clingo

% --- OUTPUT ---
% We only want the solver to return 'target' conclusions to our Python script.
#show target/2.