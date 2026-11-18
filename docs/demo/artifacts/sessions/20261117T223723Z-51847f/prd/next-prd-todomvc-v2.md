# PRD: TodoMVC (example app under test)

Target: https://demo.playwright.dev/todomvc

## UC-1 Add todos
### AC-1.1 Typing a title and pressing Enter adds it to the list
### AC-1.2 Titles that are empty or only spaces are not added
### AC-1.3 The counter shows "1 item left" after the first todo

## UC-2 Complete todos
### AC-2.1 Clicking the checkbox marks a todo completed
### AC-2.2 "Toggle all" completes every todo
### AC-2.3 "Clear completed" removes completed todos
### AC-2.4 Completed todos are shown with a strikethrough

## UC-3 Filter
### AC-3.1 "Active" shows only open todos
### AC-3.2 "Completed" shows only completed todos
### AC-3.3 The selected filter is highlighted and reflected in the URL hash

## UC-4 Edit and delete
### AC-4.1 Double-clicking a todo opens it for editing
### AC-4.2 Saving an empty edit deletes the todo
### AC-4.3 The destroy button removes a todo

## UC-5 Persistence
### AC-5.1 Todos survive a page reload
