// script.js - Core JavaScript logic for VividTask

// Global tasks array
let tasks = [];

// DOM elements
const taskForm = document.getElementById('taskForm');
const taskInput = document.getElementById('taskInput');
const taskList = document.getElementById('taskList');
const clearCompletedBtn = document.getElementById('clearCompleted');

// localStorage functions
function saveTasksToStorage() {
    localStorage.setItem('vividTasks', JSON.stringify(tasks));
}

function loadTasksFromStorage() {
    const storedTasks = localStorage.getItem('vividTasks');
    if (storedTasks) {
        tasks = JSON.parse(storedTasks);
    }
}

// Render the task list
function renderTaskList() {
    // Clear the current list
    taskList.innerHTML = '';

    // Create list items for each task
    tasks.forEach(task => {
        const li = document.createElement('li');
        li.className = 'task-item';
        li.dataset.id = task.id;

        // Add completed class if task is done
        if (task.completed) {
            li.classList.add('completed');
        }

        // Create checkbox
        const checkbox = document.createElement('button');
        checkbox.className = 'task-checkbox';
        checkbox.setAttribute('aria-label', task.completed ? 'Mark as incomplete' : 'Mark as complete');
        checkbox.innerHTML = task.completed ? '✓' : '';

        // Create task text
        const taskText = document.createElement('span');
        taskText.className = 'task-text';
        taskText.textContent = task.text;

        // Append elements
        li.appendChild(checkbox);
        li.appendChild(taskText);
        taskList.appendChild(li);
    });

    // Update clear completed button visibility
    updateClearButtonVisibility();
}

// Update clear completed button visibility
function updateClearButtonVisibility() {
    const hasCompleted = tasks.some(task => task.completed);
    clearCompletedBtn.style.display = hasCompleted ? 'block' : 'none';
}

// Generate a unique ID for tasks
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Add a new task
function addTask(text) {
    if (!text.trim()) return;

    const newTask = {
        id: generateId(),
        text: text.trim(),
        completed: false,
        createdAt: new Date().toISOString()
    };

    tasks.push(newTask);
    saveTasksToStorage();
    renderTaskList();
}

// Toggle task completion
function toggleTaskCompletion(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (task) {
        task.completed = !task.completed;
        saveTasksToStorage();
        renderTaskList();
    }
}

// Clear all completed tasks
function clearCompletedTasks() {
    tasks = tasks.filter(task => !task.completed);
    saveTasksToStorage();
    renderTaskList();
}

// Event Listeners
taskForm.addEventListener('submit', function(e) {
    e.preventDefault();
    addTask(taskInput.value);
    taskInput.value = '';
    taskInput.focus();
});

taskList.addEventListener('click', function(e) {
    const listItem = e.target.closest('.task-item');
    if (!listItem) return;

    const taskId = listItem.dataset.id;

    // Check if checkbox was clicked
    if (e.target.classList.contains('task-checkbox')) {
        toggleTaskCompletion(taskId);
    }
});

clearCompletedBtn.addEventListener('click', clearCompletedTasks);

// Initialize the app
function init() {
    loadTasksFromStorage();
    renderTaskList();
    taskInput.focus();
}

// Start the application when DOM is loaded
document.addEventListener('DOMContentLoaded', init);