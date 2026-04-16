import { useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { LogOut, Upload as UploadIcon, FileJson, CheckCircle } from 'lucide-react'
import axios from 'axios'

export default function Dashboard({ session }) {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleSignOut = async () => {
    await supabase.auth.signOut()
  }

  const handleFileChange = (e) => {
    setFile(e.target.files[0])
    setResult(null)
    setError(null)
  }

  const handleUpload = async (e) => {
    e.preventDefault()
    if (!file) return

    setUploading(true)
    setError(null)
    setResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      // Get current valid session token
      const { data: { session: currentSession } } = await supabase.auth.getSession()
      const token = currentSession?.access_token

      const response = await axios.post('http://127.0.0.1:8000/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'Authorization': `Bearer ${token}`
        }
      })
      
      setResult(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <h1 className="text-xl font-bold text-gray-900">Secure Analytics Pro</h1>
            </div>
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-500">{session.user.email}</span>
              <button
                onClick={handleSignOut}
                className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-gray-500 hover:text-gray-700 focus:outline-none transition ease-in-out duration-150"
              >
                <LogOut className="h-4 w-4 mr-1" />
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto py-10 px-4 sm:px-6 lg:px-8">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-8">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Upload Dataset (CSV)</h2>
          
          <form onSubmit={handleUpload} className="space-y-4">
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 flex flex-col items-center">
              <UploadIcon className="h-12 w-12 text-gray-400 mb-4" />
              <input
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 cursor-pointer"
              />
            </div>
            
            <button
              type="submit"
              disabled={!file || uploading}
              className="w-full sm:w-auto inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              {uploading ? 'Processing...' : 'Analyze Data'}
            </button>
          </form>

          {error && (
            <div className="mt-4 p-4 bg-red-50 text-red-700 rounded-md border border-red-200">
              {error}
            </div>
          )}

          {result && (
            <div className="mt-6 border border-green-200 rounded-md overflow-hidden">
              <div className="bg-green-50 p-4 border-b border-green-200 flex items-center">
                <CheckCircle className="h-5 w-5 text-green-500 mr-2" />
                <h3 className="text-green-800 font-medium text-sm">Analysis Summary</h3>
              </div>
              <div className="p-4 bg-white">
                <div className="grid grid-cols-2 gap-4 mb-6">
                  <div className="bg-gray-50 p-3 rounded-md border border-gray-100">
                    <span className="block text-xs font-medium text-gray-500">Total Rows</span>
                    <span className="block text-2xl font-bold text-gray-900">{result.rows}</span>
                  </div>
                  <div className="bg-gray-50 p-3 rounded-md border border-gray-100">
                    <span className="block text-xs font-medium text-gray-500">Total Columns</span>
                    <span className="block text-2xl font-bold text-gray-900">{result.columns.length}</span>
                  </div>
                </div>
                
                <div>
                  <h4 className="text-sm font-medium text-gray-700 flex items-center mb-2">
                    <FileJson className="h-4 w-4 mr-1 text-gray-500" />
                    Data Preview (First 5 records)
                  </h4>
                  <div className="overflow-x-auto">
                    <pre className="text-xs text-gray-700 bg-gray-50 p-4 rounded border border-gray-200">
                      {JSON.stringify(result.preview, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
