// DOM Elements
const chatHistory = document.getElementById('chat-history');
const userInput = document.getElementById('user-input');
const sendButton = document.getElementById('send-button');

// Store User ID
let currentUserId = null;

// Mock Product Data (For Demonstration)
const mockProducts = [
    {
        title: "Zafu Maharaja - Almofada pufe",
        price: "R$ 230,00",
        image: "https://medusa-yogateria-staging.s3.sa-east-1.amazonaws.com/zafu-maharaja-ameixa.jpg",
        url: "https://yogateria.com.br/produto/zafu-maharaja-almofada-pufe/"
    },
    {
        title: "Tapete de Yoga Premium",
        price: "R$ 450,00",
        image: "https://medusa-yogateria-staging.s3.sa-east-1.amazonaws.com/yogateria-almofada-zafu-maharaja-bege_1.png",
        url: "https://yogateria.com.br/"
    },
    {
        title: "Bloco de Yoga em Cortiça",
        price: "R$ 89,00",
        image: "https://medusa-yogateria-staging.s3.sa-east-1.amazonaws.com/yogateria-almofada-zafu-maharaja-preto_1.png",
        url: "https://yogateria.com.br/"
    }
];

// Helper: Create a message element
function createMessage(content, role = 'user') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerText = content;

    messageDiv.appendChild(bubble);
    return messageDiv;
}

// Helper: Create product card
function createProductCard(product) {
    const card = document.createElement('div');
    card.className = 'product-card';

    card.innerHTML = `
        <img src="${product.image}" alt="${product.title}" class="product-image">
        <div class="product-info">
            <h3 class="product-title">${product.title}</h3>
            <span class="product-price">${product.price}</span>
            ${product.variant_label ? `<span class="product-variant">${product.variant_label}</span>` : ''}
            <a href="${product.url}" target="_blank" class="view-btn">View Product</a>
        </div>
    `;

    return card;
}

// Helper: Create order card
function createOrderCard(order) {
    console.log('createOrderCard called with:', order);
    
    const card = document.createElement('div');
    card.className = 'order-card';
    
    // Status translation and color mapping
    const statusTranslation = {
        'Em aberto': 'Open',
        'Preparando envio': 'Preparing Shipment',
        'Cancelado': 'Cancelled',
        'Enviado': 'Shipped',
        'Entregue': 'Delivered'
    };
    
    const statusColors = {
        'Em aberto': '#FFF3CD',
        'Preparando envio': '#CCE5FF',
        'Cancelado': '#F8D7DA',
        'Enviado': '#D4EDDA',
        'Entregue': '#D4EDDA'
    };
    
    const statusText = statusTranslation[order.status] || order.status;
    const statusBgColor = statusColors[order.status] || '#E2E3E5';
    
    card.innerHTML = `
        <div class="order-info">
            <h3 class="order-title">Order #${order.order_id}</h3>
            <span class="order-status" style="background-color: ${statusBgColor}; color: #000;">${statusText}</span>
            <p class="order-date"><strong>Order Date:</strong> ${order.order_date}</p>
            <p class="order-total"><strong>Order Total:</strong> R$ ${order.total.toFixed(2)}</p>
            <a href="#" class="view-btn" onclick="event.preventDefault(); console.log('View order ${order.order_id}');">View Order</a>
        </div>
    `;
    
    console.log('Card created:', card);
    return card;
}

// Function to handle sending message
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    // 1. Add User Message
    chatHistory.appendChild(createMessage(text, 'user'));
    userInput.value = '';

    // Scroll to bottom
    scrollToBottom();

    // Check if we need to set the User ID, or if the user is explicitly passing one
    let isLogin = false;
    if (text.match(/^cus_[a-zA-Z0-9]+$/)) {
        currentUserId = text;
        isLogin = true;
    } else if (text.match(/^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/)) {
        currentUserId = text;
        isLogin = true;
    } else if (text.match(/cus_[a-zA-Z0-9]+/)) {
        currentUserId = text.match(/cus_[a-zA-Z0-9]+/)[0];
    } else if (text.match(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/)) {
        currentUserId = text.match(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/)[0];
    }

    if (!currentUserId && text) {
        currentUserId = text;
        isLogin = true;
    }

    if (isLogin) {
        let displayUser = currentUserId;
        try {
            const res = await fetch(`http://localhost:8005/user/${currentUserId}`);
            if (res.ok) {
                const userData = await res.json();
                if (userData.name) {
                    displayUser = userData.name;
                }
            }
        } catch (e) {
            console.error('Error fetching user info:', e);
        }

        const aiMsg = createMessage(`Thank you! You are now logged in as ${displayUser}. How can I help you with your order or any of our products today?`, 'ai');
        chatHistory.appendChild(aiMsg);
        scrollToBottom();
        return;
    }

    // 2. AI Thinking State
    const thinkingId = 'thinking-' + Date.now();
    const aiMsg = createMessage('Thinking...', 'ai');
    aiMsg.id = thinkingId;
    chatHistory.appendChild(aiMsg);
    scrollToBottom();

    try {
        // 3. Real API Call to Localhost
        const response = await fetch('http://localhost:8005/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: text, user_id: currentUserId })
        });

        if (!response.ok) throw new Error('Server issues');

        const data = await response.json();
        
        // Debug: Log the response data
        console.log('Backend response:', data);
        console.log('Orders data:', data.orders);

        // Update thinking message
        const bubble = aiMsg.querySelector('.bubble');

        // 4. Show Product Cards if available - BEFORE answer is shown (and visually above)
        if (data.products && data.products.length > 0) {
            const productsContainer = document.createElement('div');
            productsContainer.className = 'products-container';

            // Insert cards BEFORE the text bubble
            aiMsg.insertBefore(productsContainer, bubble);

            // Add cards one by one with a small delay
            for (const product of data.products) {
                const card = createProductCard(product);
                productsContainer.appendChild(card);
                scrollToBottom();
                await new Promise(r => setTimeout(r, 200));
            }
        }

        // 5. Show Order Cards if available - BEFORE answer is shown
        if (data.orders && data.orders.length > 0) {
            console.log('Creating order cards - count:', data.orders.length);
            const ordersContainer = document.createElement('div');
            ordersContainer.className = 'orders-container';

            // Insert cards BEFORE the text bubble
            aiMsg.insertBefore(ordersContainer, bubble);

            // Add cards one by one with a small delay
            for (const order of data.orders) {
                console.log('Creating card for order:', order);
                const card = createOrderCard(order);
                ordersContainer.appendChild(card);
                scrollToBottom();
                await new Promise(r => setTimeout(r, 200));
            }
        } else {
            console.log('No orders to display or orders array is empty/null');
        }

        // Render Markdown Response directly
        // Using marked.parse() ensures proper HTML rendering (including tables) and preserves spaces
        bubble.innerHTML = marked.parse(data.response);

        // Add feedback buttons if we have a message ID
        if (data.message_id) {
            const feedbackContainer = document.createElement('div');
            feedbackContainer.className = 'feedback-container';

            // Inline SVGs to ensure they render immediately without library dependencies
            const thumbsUpSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/></svg>`;

            const thumbsDownSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"/></svg>`;

            const label = document.createElement('span');
            label.innerText = 'Helpful? ';
            label.style.fontSize = '0.75rem';
            label.style.color = '#666';
            label.style.display = 'flex';
            label.style.alignItems = 'center';

            const upBtn = document.createElement('button');
            upBtn.className = 'feedback-btn';
            upBtn.innerHTML = thumbsUpSvg;

            const downBtn = document.createElement('button');
            downBtn.className = 'feedback-btn';
            downBtn.innerHTML = thumbsDownSvg;

            upBtn.onclick = () => submitFeedback(data.message_id, 'up', upBtn, downBtn);
            downBtn.onclick = () => submitFeedback(data.message_id, 'down', downBtn, upBtn);

            feedbackContainer.appendChild(label);
            feedbackContainer.appendChild(upBtn);
            feedbackContainer.appendChild(downBtn);

            aiMsg.appendChild(feedbackContainer);
        }

        // Render Follow-ups
        if (data.follow_ups && data.follow_ups.length > 0) {
            const followUpsContainer = document.createElement('div');
            followUpsContainer.className = 'follow-ups-container';
            const followUpsTitle = document.createElement('div');
            followUpsTitle.className = 'follow-ups-title';
            followUpsTitle.innerText = 'Follow-ups';
            followUpsContainer.appendChild(followUpsTitle);

            data.follow_ups.forEach(q => {
                const item = document.createElement('div');
                item.className = 'follow-up-item';
                item.innerHTML = `&#8618; ${q}`;
                item.onclick = () => {
                    userInput.value = q;
                    sendMessage();
                };
                followUpsContainer.appendChild(item);
            });
            aiMsg.appendChild(followUpsContainer);
        }

    } catch (error) {
        console.error('Error:', error);
        aiMsg.querySelector('.bubble').innerText = "I'm having trouble connecting to the server. Please make sure the backend is running at localhost:8005.";
    }

    scrollToBottom();
}

async function submitFeedback(messageId, type, activeBtn, otherBtn) {
    try {
        const response = await fetch('http://localhost:8005/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: messageId, feedback: type })
        });

        if (response.ok) {
            activeBtn.classList.add('active');
            otherBtn.classList.remove('active');
            activeBtn.parentElement.classList.add('has-feedback');
        }
    } catch (e) {
        console.error('Feedback error:', e);
    }
}

function scrollToBottom() {
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Event Listeners
sendButton.addEventListener('click', sendMessage);

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

// Auto-focus input
window.addEventListener('load', () => {
    userInput.focus();
});
