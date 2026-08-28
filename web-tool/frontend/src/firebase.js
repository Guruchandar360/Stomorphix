import { initializeApp } from "firebase/app";
import { getAuth, getIdToken, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "firebase/auth";

const getEnvVal = (key) => {
  if (typeof window !== "undefined" && window.env && window.env[key]) {
    return window.env[key];
  }
  return import.meta.env[key];
};

const firebaseConfig = {
  apiKey: getEnvVal("VITE_FIREBASE_API_KEY"),
  authDomain: getEnvVal("VITE_FIREBASE_AUTH_DOMAIN"),
  projectId: getEnvVal("VITE_FIREBASE_PROJECT_ID"),
  storageBucket: getEnvVal("VITE_FIREBASE_STORAGE_BUCKET"),
  messagingSenderId: getEnvVal("VITE_FIREBASE_MESSAGING_SENDER_ID"),
  appId: getEnvVal("VITE_FIREBASE_APP_ID")
};

const isConfigValid = !!(
  firebaseConfig.apiKey &&
  firebaseConfig.authDomain &&
  firebaseConfig.projectId
);

let app;
let auth;
let googleProvider;
let firebaseSignInWithPopup = signInWithPopup;
let firebaseSignOut = signOut;
let firebaseOnAuthStateChanged = onAuthStateChanged;

if (isConfigValid) {
  try {
    app = initializeApp(firebaseConfig);
    auth = getAuth(app);
    googleProvider = new GoogleAuthProvider();
  } catch (error) {
    console.error("Firebase initialization failed:", error);
    setupMockAuth();
  }
} else {
  console.warn("Firebase environment variables are missing. Using fallback mock auth system.");
  setupMockAuth();
}

function setupMockAuth() {
  let mockUser = null;
  try {
    const cached = localStorage.getItem("mock_firebase_user");
    if (cached) mockUser = JSON.parse(cached);
  } catch (e) {
    console.error("Failed to parse mock user:", e);
  }

  const listeners = [];
  const setMockUser = (user) => {
    mockUser = user;
    auth.currentUser = user;
    if (user) {
      localStorage.setItem("mock_firebase_user", JSON.stringify(user));
    } else {
      localStorage.removeItem("mock_firebase_user");
    }
    listeners.forEach((cb) => cb(user));
  };

  auth = { currentUser: mockUser };
  googleProvider = {};

  firebaseOnAuthStateChanged = (authObj, cb) => {
    listeners.push(cb);
    cb(mockUser);
    return () => {
      const idx = listeners.indexOf(cb);
      if (idx > -1) listeners.splice(idx, 1);
    };
  };

  firebaseSignInWithPopup = (authObj, providerObj) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        const dummyUser = {
          uid: "mock_user_123",
          displayName: "Mock Scientist",
          email: "scientist@example.com",
          photoURL: "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y"
        };
        setMockUser(dummyUser);
        resolve({ user: dummyUser });
      }, 1000);
    });
  };

  firebaseSignOut = (authObj) => {
    return new Promise((resolve) => {
      setMockUser(null);
      resolve();
    });
  };
}

async function getAuthToken() {
  if (!isConfigValid || !auth?.currentUser) return "";
  return getIdToken(auth.currentUser);
}

export {
  auth,
  googleProvider,
  firebaseSignInWithPopup as signInWithPopup,
  firebaseSignOut as signOut,
  firebaseOnAuthStateChanged as onAuthStateChanged,
  getAuthToken
};
