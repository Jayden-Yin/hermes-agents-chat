const path = require('path');

module.exports = {
  entry: './src/index.jsx',
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'index.js',
    library: {
      name: 'HermesChatPlugin',
      type: 'umd',
      export: 'default',
    },
    globalObject: 'this',
  },
  resolve: {
    extensions: ['.js', '.jsx'],
  },
  externals: {
    // React is provided by the Dashboard SDK at runtime.
    react: {
      root: ['__HERMES_PLUGIN_SDK__', 'React'],
      commonjs: 'react',
      commonjs2: 'react',
      amd: 'react',
    },
    // react-dom is NOT provided by the Dashboard SDK and the plugin
    // does not need it (Dashboard handles mounting). Remove external
    // so webpack bundles react-dom (tree-shaken if unused).
  },
  module: {
    rules: [
      {
        test: /\.(js|jsx)$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
          options: {
            presets: [
              '@babel/preset-env',
              ['@babel/preset-react', { runtime: 'classic' }],
            ],
          },
        },
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader'],
      },
    ],
  },
  devtool: 'source-map',
};
