importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.7.1/firebase-messaging-compat.js');

const firebaseConfig = {
  apiKey: "AIzaSyDZmi5sFcGz3PjdRPanAQcj54oeENo2ejI",
  authDomain: "hackathon-f95fe.firebaseapp.com",
  projectId: "hackathon-f95fe",
  storageBucket: "hackathon-f95fe.firebasestorage.app",
  messagingSenderId: "1056217574820",
  appId: "1:1056217574820:web:6090e83629e951d6212531",
  measurementId: "G-21PP3H88NE"
};

if (firebaseConfig.apiKey) {
    firebase.initializeApp(firebaseConfig);
    const messaging = firebase.messaging();

    messaging.onBackgroundMessage((payload) => {
        console.log('[firebase-messaging-sw.js] Otrzymano powiadomienie w tle: ', payload);
        const notificationTitle = payload.notification.title;
        const notificationOptions = {
            body: payload.notification.body,
            icon: '/static/favicon.ico'
        };

        self.registration.showNotification(notificationTitle, notificationOptions);
    });
}
