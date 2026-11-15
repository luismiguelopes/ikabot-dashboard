import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'
import { AuthGate } from './components/AuthGate'
import { ErrorBoundary } from './components/ErrorBoundary'
import { installAuthInterceptor } from './api'

installAuthInterceptor()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthGate>
      <ErrorBoundary label="app">
        <App />
      </ErrorBoundary>
    </AuthGate>
  </React.StrictMode>
)
