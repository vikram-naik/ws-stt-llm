// ui.js (/static/ui.js)
console.log('ui.js loaded');

// Define global user lists
window.sales = [];
window.customers = [];

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded');

    // Set default language based on OS locale
    try {
        const userLang = navigator.language.split('-')[0];
        const langSelect = document.getElementById('language');
        if (!langSelect) throw new Error('Language select element not found');
        if (userLang === 'en' || userLang === 'ja') {
            langSelect.value = userLang;
        } else {
            langSelect.value = 'en';
        }
    } catch (error) {
        console.error('Error setting language:', error);
    }

    // Store current user's group
    let currentGroup = null;

    // Entry form submission
    try {
        const entryForm = document.getElementById('entryForm');
        if (!entryForm) throw new Error('Entry form not found');
        entryForm.addEventListener('submit', (e) => {
            try {
                e.preventDefault();
                const group = document.querySelector('input[name="group"]:checked').value;
                const username = document.getElementById('username').value;
                console.log('Registering:', { group, username });
                currentGroup = group;
                const header = document.getElementById('userListHeader');
                if (!header) throw new Error('User list header not found');
                if (group === 'sales') {
                    header.textContent = 'Customers';
                } else {
                    header.textContent = 'Sales Team';
                    document.getElementById('conversationPanel').classList.add('d-none');
                }
                const userNameSpan = document.getElementById('userName').querySelector('span');
                userNameSpan.textContent = username;
                userNameSpan.classList.add(group === 'sales' ? 'text-primary' : 'text-secondary');
                document.getElementById('logoutBtn').classList.remove('d-none');
                register(group, username);
            } catch (error) {
                console.error('Error in form submission:', error);
            }
        });
    } catch (error) {
        console.error('Error setting up form listener:', error);
    }

    // Logout
    try {
        const logoutBtn = document.getElementById('logoutBtn');
        if (!logoutBtn) throw new Error('Logout button not found');
        logoutBtn.addEventListener('click', () => {
            try {
                socket.send(JSON.stringify({ event: 'logout', username: currentCall.username }));
                document.cookie = 'session_id=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
                document.getElementById('mainUI').classList.add('d-none');
                document.getElementById('entryScreen').classList.remove('d-none');
                document.getElementById('transcription').classList.add('d-none');
                logoutBtn.classList.add('d-none');
            } catch (error) {
                console.error('Error in logout:', error);
            }
        });
    } catch (error) {
        console.error('Error setting up logout listener:', error);
    }

    window.updatePartial = function(text, group) {
        try {
            const bubbleId = group === 'sales' ? 'sales-partial-bubble' : 'customers-partial-bubble';
            const usernameId = group === 'sales' ? 'sales-partial-username' : 'customers-partial-username';
            const partialBubble = document.getElementById(bubbleId);
            const usernameSpan = document.getElementById(usernameId);
            const container = partialBubble.parentElement; // .bubble-container
            if (!partialBubble) throw new Error(`${bubbleId} element not found`);
            if (!usernameSpan) throw new Error(`${usernameId} element not found`);
            if (!currentCall.call_id) {
                container.style.display = 'none';
                return;
            }
            container.style.display = 'block';
            partialBubble.innerHTML = text || '';
            usernameSpan.textContent = group === 'sales' ? currentCall.username : currentCall.peer?.to_user || currentCall.peer?.from_user || '';
            partialBubble.scrollTop = partialBubble.scrollHeight;
        } catch (error) {
            console.error('Error in updatePartial:', error);
        }
    };

    window.addFinal = function(text, group) {
        try {
            const finals = document.getElementById('finals');
            if (!finals) throw new Error('Finals element not found');
            const bubbleContainer = document.createElement('div');
            bubbleContainer.className = 'bubble-container';
            const usernameSpan = document.createElement('span');
            usernameSpan.className = 'bubble-username';
            usernameSpan.textContent = group === 'sales' ? currentCall.username : currentCall.peer?.to_user || currentCall.peer?.from_user || '';
            const bubble = document.createElement('div');
            bubble.className = `chat-bubble-${group}`;
            bubble.innerHTML = text;
            bubbleContainer.appendChild(usernameSpan);
            bubbleContainer.appendChild(bubble);
            finals.appendChild(bubbleContainer);
            finals.scrollTop = finals.scrollHeight;
            const bubbleId = group === 'sales' ? 'sales-partial-bubble' : 'customers-partial-bubble';
            const partialBubble = document.getElementById(bubbleId);
            if (partialBubble) partialBubble.innerHTML = '';
        } catch (error) {
            console.error('Error in addFinal:', error);
        }
    };

    window.updateUserList = function({ sales: newSales, customers: newCustomers }) {
        try {
            console.log('updateUserList called with:', { newSales, newCustomers, currentGroup, callId: currentCall.call_id, peer: currentCall.peer });
            window.sales = newSales || window.sales;
            window.customers = newCustomers || window.customers;
            const userList = document.getElementById('userList');
            if (!userList) throw new Error('User list element not found');
            userList.innerHTML = '';
            const usersToShow = currentGroup === 'sales' ? window.customers : window.sales;
            if (!Array.isArray(usersToShow)) throw new Error('usersToShow is not an array');
            usersToShow.forEach(username => {
                const li = document.createElement('li');
                li.className = `list-group-item ${currentGroup === 'sales' ? 'customer-bg' : 'sales-bg'} d-flex align-items-center`;
                const inCall = currentCall.call_id && (username === currentCall.peer?.from_user || username === currentCall.peer?.to_user);
                li.innerHTML = `
                    <i class="bi bi-person me-2"></i>
                    <span>${username}</span>
                    ${inCall ?
                        `<button class="btn btn-danger btn-sm ms-auto hangup-btn" onclick="window.hangUp()">
                            <i class="bi bi-telephone-x-fill"></i>
                        </button>` :
                        `<button class="btn btn-sm ms-auto call-btn" onclick="window.callUser('${username}')" ${currentCall.call_id ? 'disabled' : ''}>
                            <i class="bi bi-telephone-fill"></i>
                        </button>`}
                `;
                userList.appendChild(li);
            });
            const logoutBtn = document.getElementById('logoutBtn');
            if (currentCall.call_id) logoutBtn.setAttribute('disabled', 'true');
            else logoutBtn.removeAttribute('disabled');
            // Hide partial bubbles if no call
            const salesContainer = document.getElementById('sales-partial-bubble')?.parentElement;
            const customersContainer = document.getElementById('customers-partial-bubble')?.parentElement;
            if (salesContainer) salesContainer.style.display = currentCall.call_id ? 'block' : 'none';
            if (customersContainer) customersContainer.style.display = currentCall.call_id ? 'block' : 'none';
        } catch (error) {
            console.error('Error in updateUserList:', error);
        }
    };

    window.showIncomingCall = function(fromUser, callId) {
        try {
            console.log('Showing incoming call from:', fromUser, 'callId:', callId);
            const callerText = document.getElementById('callerText');
            if (!callerText) throw new Error('Caller text element not found');
            callerText.textContent = `${fromUser} is calling...`;
            const incomingModal = new bootstrap.Modal(document.getElementById('incomingCall'));
            incomingModal.show();
            document.getElementById('acceptCall').onclick = () => {
                window.acceptCall();
                window.updateUserList({ sales: window.sales, customers: window.customers });
                incomingModal.hide();
            };
            document.getElementById('rejectCall').onclick = () => {
                window.rejectCall();
                window.updateUserList({ sales: window.sales, customers: window.customers });
                incomingModal.hide();
            };
        } catch (error) {
            console.error('Error in showIncomingCall:', error);
        }
    };

    window.callAccepted = function() {
        try {
            console.log('callAccepted triggered');
            updatePartial('', 'sales');
            updatePartial('', 'customers');
            window.updateUserList({ sales: window.sales, customers: window.customers });
            bootstrap.Modal.getInstance(document.getElementById('incomingCall'))?.hide();
        } catch (error) {
            console.error('Error in callAccepted:', error);
        }
    };

    window.callEnded = function() {
        try {
            console.log('Call ended');
            updatePartial('', 'sales');
            updatePartial('', 'customers');
            window.updateUserList({ sales: window.sales, customers: window.customers });
            bootstrap.Modal.getInstance(document.getElementById('incomingCall'))?.hide();
        } catch (error) {
            console.error('Error in callEnded:', error);
        }
    };

    window.addInsight = function(text) {
        try {
            const insightsList = document.getElementById('insightsList');
            if (!insightsList) throw new Error('Insights list element not found');
            const li = document.createElement('li');
            li.className = 'list-group-item';
            li.textContent = text;
            insightsList.appendChild(li);
            insightsList.scrollTop = insightsList.scrollHeight;
        } catch (error) {
            console.error('Error in addInsight:', error);
        }
    };

    window.showError = function(message) {
        try {
            console.log('Showing error:', message);
            alert(message);
        } catch (error) {
            console.error('Error in showError:', error);
        }
    };

    window.showMainUI = function(group) {
        try {
            document.getElementById('entryScreen').classList.add('d-none');
            document.getElementById('mainUI').classList.remove('d-none');
            if (group === 'sales') {
                document.getElementById('transcription').classList.remove('d-none');
            } else {
                document.getElementById('transcription').classList.add('d-none');
            }
        } catch (error) {
            console.error('Error in showMainUI:', error);
        }
    };
});